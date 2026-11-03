"""GitHub 监控：仓库导入、版本检测、Webhook 验签、去重、推送与重试。"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from app.core.http import set_transport
from app.services.account_manager import account_manager

REPO_PAYLOAD = {
    "id": 1,
    "name": "hello",
    "full_name": "octocat/hello",
    "html_url": "https://github.com/octocat/hello",
    "description": "一个用于测试的开源音乐播放器",
    "default_branch": "main",
    "language": "Python",
    "stargazers_count": 42,
    "forks_count": 7,
    "owner": {"login": "octocat"},
}

RELEASE_V1 = {
    "tag_name": "v1.0.0",
    "name": "1.0.0 首个版本",
    "body": "## 更新内容\n- 初始版本",
    "html_url": "https://github.com/octocat/hello/releases/tag/v1.0.0",
    "prerelease": False,
    "draft": False,
    "assets": [],
    "published_at": "2026-10-01T10:00:00Z",
}


def _release(tag: str, *, prerelease: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": f"版本 {tag}",
        "body": "## 新增\n- 新增功能 A\n## 修复\n- 修复问题 B",
        "html_url": f"https://github.com/octocat/hello/releases/tag/{tag}",
        "prerelease": prerelease,
        "draft": False,
        "assets": [
            {
                "name": "player-windows.zip",
                "size": 1048576,
                "browser_download_url": f"https://github.com/octocat/hello/releases/download/{tag}/player-windows.zip",
            }
        ],
        "published_at": "2026-11-03T02:00:00Z",
    }


@pytest.fixture(autouse=True)
def github_transport():
    state = {"releases": [RELEASE_V1]}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/octocat/hello":
            return httpx.Response(200, json=REPO_PAYLOAD)
        if path.endswith("/releases"):
            return httpx.Response(200, json=state["releases"])
        if path.endswith("/tags"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "Not Found"})

    github_transport.state = state  # type: ignore[attr-defined]
    set_transport(httpx.MockTransport(handler))
    yield state
    set_transport(None)


async def _add_repo(client: httpx.AsyncClient, headers: dict) -> dict:
    repos = (await client.get("/api/github/repos", headers=headers)).json()
    existing = next((r for r in repos if r["full_name"] == "octocat/hello"), None)
    if existing:
        return existing
    created = await client.post(
        "/api/github/repos",
        headers=headers,
        json={"url": "https://github.com/octocat/hello", "poll_interval_seconds": 600},
    )
    assert created.status_code == 201, created.text
    return created.json()


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_add_repo_imports_history_without_push(
    client: httpx.AsyncClient, admin_headers: dict, mock_account: dict
):
    repo = await _add_repo(client, admin_headers)
    assert repo["default_branch"] == "main"
    assert repo["description"].startswith("一个用于测试")
    assert repo["last_release_tag"] == "v1.0.0"
    assert repo["release_count"] >= 1
    records = (await client.get("/api/github/push-records", headers=admin_headers)).json()
    assert all(r["release_tag"] != "v1.0.0" for r in records["items"])

    check = await client.post(f"/api/github/repos/{repo['id']}/check", headers=admin_headers)
    assert check.status_code == 200
    assert check.json()["ok"] is True
    assert check.json()["new_releases"] == 0


async def test_webhook_signature_and_push(
    client: httpx.AsyncClient, admin_headers: dict, mock_account: dict, github_transport: dict
):
    repo = await _add_repo(client, admin_headers)
    secret = "whsec-test-secret"
    await client.put(f"/api/github/repos/{repo['id']}", headers=admin_headers, json={"webhook_secret": secret})

    rule = await client.post(
        "/api/github/push-rules",
        headers=admin_headers,
        json={
            "repository_id": repo["id"],
            "account_id": mock_account["id"],
            "qq_group": 900001,
            "ai_summary": False,
            "only_stable": True,
            "mention_user_ids": [20001],
        },
    )
    assert rule.status_code == 201, rule.text

    payload = {"action": "published", "release": _release("v2.0.0"), "repository": {"full_name": "octocat/hello"}}
    body = json.dumps(payload).encode()
    bad = await client.post(
        f"/api/webhook/github/{repo['id']}",
        content=body,
        headers={"x-github-event": "release", "x-github-delivery": "delivery-bad", "x-hub-signature-256": "sha256=deadbeef", "content-type": "application/json"},
    )
    assert bad.status_code == 401

    ok = await client.post(
        f"/api/webhook/github/{repo['id']}",
        content=body,
        headers={
            "x-github-event": "release",
            "x-github-delivery": "delivery-1",
            "x-hub-signature-256": _sign(secret, body),
            "content-type": "application/json",
        },
    )
    assert ok.status_code == 200, ok.text
    result = ok.json()
    assert result["new_releases"] == 1
    assert result["pushed"] == 1

    adapter = account_manager.adapter(mock_account["id"])
    assert any("v2.0.0" in item["message"] for item in adapter.outbox)
    sent = next(item["message"] for item in adapter.outbox if "v2.0.0" in item["message"])
    assert "GitHub 项目更新通知" in sent
    assert "player-windows.zip" in sent
    assert "[CQ:at,qq=20001]" in sent

    # 相同 delivery 重放：必须被去重
    duplicate = await client.post(
        f"/api/webhook/github/{repo['id']}",
        content=body,
        headers={
            "x-github-event": "release",
            "x-github-delivery": "delivery-1",
            "x-hub-signature-256": _sign(secret, body),
            "content-type": "application/json",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json().get("duplicate") is True

    # 另一个 delivery 但同一版本：Release 已存在，推送记录去重
    again_body = json.dumps({**payload, "action": "published"}).encode()
    before_outbox = len(adapter.outbox)
    again = await client.post(
        f"/api/webhook/github/{repo['id']}",
        content=again_body,
        headers={
            "x-github-event": "release",
            "x-github-delivery": "delivery-2",
            "x-hub-signature-256": _sign(secret, again_body),
            "content-type": "application/json",
        },
    )
    assert again.status_code == 200
    assert len(adapter.outbox) == before_outbox, "同一 Release 不应重复推送"

    records = (await client.get("/api/github/push-records", headers=admin_headers)).json()
    v2_records = [r for r in records["items"] if r["release_tag"] == "v2.0.0"]
    assert len(v2_records) == 1
    assert v2_records[0]["status"] == "success"


async def test_prerelease_skipped(client: httpx.AsyncClient, admin_headers: dict, mock_account: dict):
    repo = await _add_repo(client, admin_headers)
    await client.put(f"/api/github/repos/{repo['id']}", headers=admin_headers, json={"webhook_secret": ""})
    body = json.dumps(
        {"action": "published", "release": _release("v3.0.0-beta.1", prerelease=True), "repository": {"full_name": "octocat/hello"}}
    ).encode()
    resp = await client.post(
        f"/api/webhook/github/{repo['id']}",
        content=body,
        headers={"x-github-event": "release", "x-github-delivery": "delivery-pre", "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["pushed"] == 0


async def test_failed_push_then_retry(client: httpx.AsyncClient, admin_headers: dict, mock_account: dict):
    repo = await _add_repo(client, admin_headers)
    await client.put(f"/api/github/repos/{repo['id']}", headers=admin_headers, json={"webhook_secret": ""})
    # The session-scoped test database retains earlier tests' data. Disable their
    # rules so this test verifies only the explicitly offline destination account.
    existing_rules = (await client.get("/api/github/push-rules", headers=admin_headers)).json()
    for existing_rule in existing_rules:
        if existing_rule["repository_id"] == repo["id"]:
            await client.put(
                f"/api/github/push-rules/{existing_rule['id']}",
                headers=admin_headers,
                json={"enabled": False},
            )
    created = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json={"name": "离线推送账号", "protocol": "mock", "connection_mode": "http", "qq_number": 300003},
    )
    offline_account = created.json()
    rule = await client.post(
        "/api/github/push-rules",
        headers=admin_headers,
        json={
            "repository_id": repo["id"],
            "account_id": offline_account["id"],
            "qq_group": 900002,
            "ai_summary": False,
        },
    )
    assert rule.status_code == 201

    body = json.dumps(
        {"action": "published", "release": _release("v4.0.0"), "repository": {"full_name": "octocat/hello"}}
    ).encode()
    resp = await client.post(
        f"/api/webhook/github/{repo['id']}",
        content=body,
        headers={"x-github-event": "release", "x-github-delivery": "delivery-offline", "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["pushed"] == 0

    records = (await client.get("/api/github/push-records?status=failed", headers=admin_headers)).json()
    failed = next(
        r for r in records["items"] if r["release_tag"] == "v4.0.0" and r["account_id"] == offline_account["id"]
    )
    assert "不在线" in (failed["error"] or "")

    started = await client.post(f"/api/accounts/{offline_account['id']}/start", headers=admin_headers)
    assert started.status_code == 200
    for _ in range(30):
        if account_manager.is_online(offline_account["id"]):
            break
        import asyncio

        await asyncio.sleep(0.1)

    retried = await client.post(f"/api/github/push-records/{failed['id']}/retry", headers=admin_headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["ok"] is True

    adapter = account_manager.adapter(offline_account["id"])
    assert any("v4.0.0" in item["message"] for item in adapter.outbox)
    await client.delete(f"/api/accounts/{offline_account['id']}", headers=admin_headers)
