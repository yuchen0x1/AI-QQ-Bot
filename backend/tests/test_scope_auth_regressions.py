"""Behavioral regressions for repository, OAuth, WebSocket and callback boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.base import AdapterEvent
from app.core.http import set_transport
from app.core.security import decrypt_secret, encrypt_secret, hash_password
from app.models import (
    AuthSession, GithubNotificationTarget, GithubRepository, PushRule, Role,
    ScheduledTask, SystemLog, User, UserGithubToken,
)
from app.services.commands import CommandContext, cmd_check_update, cmd_repos
from tests.fakes import FakeOfficialAdapter


def _repo(name, owner_user_id=None):
    return GithubRepository(owner="scope-test", name=name, full_name=f"scope-test/{name}",
                            html_url=f"https://github.com/scope-test/{name}", owner_user_id=owner_user_id,
                            webhook_secret_enc=encrypt_secret("scope-secret"))


def _ctx(db, account_id, *, group=900001, private=False):
    return CommandContext(db=db, account_id=account_id, account_name="scope", adapter=FakeOfficialAdapter(),
                          event=AdapterEvent(post_type="message", message_type="private" if private else "group"),
                          group_number=None if private else group, group=None, settings=None,
                          is_private=private, sender_id=12345, sender_role="admin")


async def test_bot_repository_listing_requires_matching_account_group_grant(client, db, mock_account):
    allowed, other_group, other_account, unmapped = [_repo(f"list-{key}") for key in ("allowed", "group", "account", "none")]
    db.add_all([allowed, other_group, other_account, unmapped])
    await db.flush()
    db.add_all([
        PushRule(repository_id=allowed.id, account_id=mock_account["id"], qq_group=900001),
        PushRule(repository_id=other_group.id, account_id=mock_account["id"], qq_group=900002),
    ])
    await db.commit()
    result = await cmd_repos(_ctx(db, mock_account["id"]))
    assert allowed.full_name in result
    assert other_group.full_name not in result
    assert other_account.full_name not in result
    assert unmapped.full_name not in result
    private = await cmd_repos(_ctx(db, mock_account["id"], private=True))
    assert "scope-test/" not in private, "Private QQ identity must not implicitly grant console repositories"


async def test_check_update_filters_before_network_and_limits_destinations(client, db, mock_account):
    allowed, excluded = _repo("check-allowed"), _repo("check-secret")
    db.add_all([allowed, excluded])
    await db.flush()
    db.add_all([
        PushRule(repository_id=allowed.id, account_id=mock_account["id"], qq_group=900001, ai_summary=False, markdown_card=False),
        PushRule(repository_id=allowed.id, account_id=mock_account["id"], qq_group=900002, ai_summary=False, markdown_card=False),
        PushRule(repository_id=excluded.id, account_id=mock_account["id"], qq_group=900002, ai_summary=False),
    ])
    await db.commit()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/releases"):
            return httpx.Response(200, json=[{"tag_name": "v9.0.1-scope", "body": "scope regression", "assets": []}])
        return httpx.Response(200, json={"full_name": allowed.full_name})

    from app.services.account_manager import account_manager
    adapter = account_manager.adapter(mock_account["id"])
    before = len(adapter.outbox)
    set_transport(httpx.MockTransport(handler))
    try:
        result = await cmd_check_update(_ctx(db, mock_account["id"]))
    finally:
        set_transport(None)
    assert "1 个仓库" in result
    assert calls and all("check-allowed" in path for path in calls), calls
    sent = adapter.outbox[before:]
    assert len(sent) == 1
    assert sent[0]["target"] == 900001


async def test_deleting_owner_archives_credentials_rules_and_task_access(client, db, admin_headers, mock_account):
    role = await db.scalar(select(Role).where(Role.name == "viewer"))
    owner = User(username="deleted-repo-owner", role_id=role.id, password_hash=hash_password("secret-password-123"))
    db.add(owner)
    await db.flush()
    owner_id = owner.id
    repo = _repo("deleted-owner", owner_id)
    repo.token_enc = encrypt_secret("private-credential")
    db.add(repo)
    await db.flush()
    rule = PushRule(repository_id=repo.id, account_id=mock_account["id"], qq_group=900001, managed_by_user_id=owner_id)
    task = ScheduledTask(name="private owner task", task_type="github_check", enabled=True,
                         payload={"repository_id": repo.id}, created_by=owner.username)
    target = GithubNotificationTarget(user_id=owner_id, account_id=mock_account["id"], group_label="private", qq_group=900001)
    db.add_all([rule, task, target, UserGithubToken(user_id=owner_id, github_id=55500991, login="deleted-owner", access_token_enc="secret")])
    await db.commit()
    result = await client.delete(f"/api/users/{owner_id}", headers=admin_headers)
    assert result.status_code == 200, result.text
    await db.refresh(repo)
    await db.refresh(rule)
    await db.refresh(task)
    assert repo.owner_user_id == owner_id, "Deleting an owner must never convert private data to owner=NULL/global"
    assert not repo.monitor_enabled and not repo.remote_available
    assert repo.token_enc is None and repo.webhook_secret_enc is None
    assert not rule.enabled and not task.enabled
    assert await db.scalar(select(UserGithubToken.id).where(UserGithubToken.user_id == owner_id)) is None
    db.expunge(owner)
    viewer = User(username="post-delete-viewer", role_id=role.id, password_hash=hash_password("viewer-password-123"))
    db.add(viewer)
    await db.commit()
    from app.services.github.registry import can_access_repo, repo_scope_condition
    assert not can_access_repo(viewer, repo)
    assert repo.id not in set(await db.scalars(select(GithubRepository.id).where(repo_scope_condition(viewer))))


async def _oauth_start(client, headers):
    await client.put("/api/github/oauth/app", headers=headers, json={"client_id": "Iv.scope", "client_secret": "scope-secret"})
    response = await client.get("/api/github/oauth/start", headers=headers)
    assert response.status_code == 302, response.text
    return response, parse_qs(urlparse(response.headers["location"]).query)


@pytest.fixture
def oauth_mock():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "gho_scope_token", "scope": "repo"})
        return httpx.Response(200, json={"id": 93399901, "login": "scope-oauth"})

    set_transport(httpx.MockTransport(handler))
    yield calls
    set_transport(None)


async def test_oauth_browser_binding_replay_and_pkce(client, admin_headers, oauth_mock):
    _, query = await _oauth_start(client, admin_headers)
    state = query["state"][0]
    callback_path = f"/api/github/oauth/callback?state={state}&code=scope-code"
    # A second browser knows the URL but lacks the initiating HttpOnly cookie.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=__import__("app.main", fromlist=["app"]).app), base_url="http://other-browser") as stranger:
        denied = await stranger.get(callback_path)
    assert "github=error" in denied.headers["location"]
    assert oauth_mock == [], "Cross-browser callbacks must not exchange a code"
    accepted = await client.get(callback_path)
    assert "github=connected" in accepted.headers["location"]
    repeated = await client.get(callback_path)
    assert "github=error" in repeated.headers["location"]
    exchanges = [call for call in oauth_mock if call.url.path.endswith("/access_token")]
    assert len(exchanges) == 1
    assert query["code_challenge_method"] == ["S256"]
    body = parse_qs(exchanges[0].content.decode())
    verifier = body["code_verifier"][0]
    from app.services.github.oauth import pkce_challenge
    assert pkce_challenge(verifier) == query["code_challenge"][0]


async def test_oauth_rejects_revoked_originating_session(client, db, admin_headers, oauth_mock):
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    _, query = await _oauth_start(client, headers)
    from app.core.security import decode_access_token
    session = await db.scalar(select(AuthSession).where(AuthSession.jti == decode_access_token(token)["jti"]))
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    denied = await client.get(f"/api/github/oauth/callback?state={query['state'][0]}&code=revoked-code")
    assert "github=error" in denied.headers["location"]
    assert not oauth_mock


async def test_oauth_database_expiry_cannot_be_bypassed_by_valid_jwt(client, db, admin_headers, oauth_mock):
    _, query = await _oauth_start(client, admin_headers)
    from app.models import GithubOAuthState
    row = await db.scalar(select(GithubOAuthState).where(GithubOAuthState.state_hash == hashlib.sha256(query["state"][0].encode()).hexdigest()))
    assert decrypt_secret(row.code_verifier_enc)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    denied = await client.get(f"/api/github/oauth/callback?state={query['state'][0]}&code=expired-code")
    assert "github=error" in denied.headers["location"]
    assert not oauth_mock


@pytest.mark.parametrize("route_name,hub_name", [("ws_events", "event_hub"), ("ws_logs", "hub")])
async def test_active_websocket_revokes_without_waiting_for_queue_idle(monkeypatch, route_name, hub_name):
    from app.api import ws
    queue = asyncio.Queue()
    close_codes = []
    sent = 0

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, item):
            nonlocal sent
            sent += 1
            await asyncio.sleep(0)

        async def close(self, code=1000, reason=""):
            close_codes.append(code)

    async def authenticated(*args, **kwargs):
        return SimpleNamespace(permission_set={"*"})

    async def revoked(*args):
        return False

    async def subscribe():
        return queue

    async def unsubscribe(item):
        pass

    async def produce():
        while True:
            await queue.put({"type": "test", "data": {}})
            await asyncio.sleep(0.001)

    monkeypatch.setattr(ws, "_authenticate", authenticated)
    monkeypatch.setattr(ws, "_session_ref", lambda token: ("revoked-session", "admin"))
    monkeypatch.setattr(ws, "_session_alive", revoked)
    monkeypatch.setattr(ws, "WS_SESSION_RECHECK_SECONDS", 0.02, raising=False)
    target_hub = getattr(ws, hub_name)
    monkeypatch.setattr(target_hub, "subscribe", subscribe)
    monkeypatch.setattr(target_hub, "unsubscribe", unsubscribe)
    producer = asyncio.create_task(produce())
    try:
        await asyncio.wait_for(getattr(ws, route_name)(Socket(), ticket="ticket", token=None), timeout=0.3)
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
    assert sent > 2, "Test must exercise an active stream"
    assert 4401 in close_codes


async def test_invalid_github_signatures_are_sampled_and_rate_limited(client, db, monkeypatch):
    repo = _repo("signature-sampling")
    db.add(repo)
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(SystemLog).where(SystemLog.message.contains(repo.full_name)))
    for _ in range(12):
        denied = await client.post(f"/api/webhook/github/{repo.id}", content=b"{}", headers={"x-hub-signature-256": "bad"})
        assert denied.status_code == 401
    after = await db.scalar(select(func.count()).select_from(SystemLog).where(SystemLog.message.contains(repo.full_name)))
    assert after - before == 1, "A signature flood must not create one database log per unauthenticated request"
    from app.core import webhook_limits
    monkeypatch.setattr(webhook_limits.webhook_limiter, "limit", 2)
    webhook_limits.webhook_limiter._hits.clear()
    first = await client.post(f"/api/webhook/github/{repo.id}", content=b"{}")
    second = await client.post(f"/api/webhook/github/{repo.id}", content=b"{}")
    limited = await client.post(f"/api/webhook/github/{repo.id}", content=b"{}")
    assert [first.status_code, second.status_code, limited.status_code] == [401, 401, 429]
    assert int(limited.headers["retry-after"]) > 0
    webhook_limits.webhook_limiter._hits.clear()


async def test_signed_github_burst_is_not_subject_to_console_api_budget(client, db):
    repo = _repo("signed-burst")
    db.add(repo)
    await db.commit()
    from app.core.ratelimit import api_limiter
    from app.core import webhook_limits
    webhook_limits.webhook_limiter._hits.clear()
    api_limiter._hits["127.0.0.1"].extend([time.monotonic()] * api_limiter.limit)
    body = json.dumps({"zen": "signed"}).encode()
    signature = "sha256=" + hmac.new(b"scope-secret", body, hashlib.sha256).hexdigest()
    try:
        for _ in range(20):
            response = await client.post(f"/api/webhook/github/{repo.id}", content=body,
                                         headers={"x-github-event": "ping", "x-hub-signature-256": signature})
            assert response.status_code == 200, response.text
    finally:
        api_limiter._hits.clear()
        webhook_limits.webhook_limiter._hits.clear()
