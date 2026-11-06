"""GitHub OAuth：配置、授权回调、仓库导入、凭据取用与仓库归属隔离。"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.http import set_transport

OAUTH_TOKEN = "gho_test_token_1234567890"
GITHUB_USER = {
    "id": 991001,
    "login": "octocat",
    "name": "The Octocat",
    "avatar_url": "https://avatars.githubusercontent.com/u/991001",
    "email": "octocat@example.com",
}
REPO_PAYLOAD = {
    "id": 2,
    "name": "spoon-knife",
    "full_name": "octocat/spoon-knife",
    "html_url": "https://github.com/octocat/spoon-knife",
    "description": "用来验证 OAuth 导入的仓库",
    "default_branch": "main",
    "language": "Go",
    "stargazers_count": 3,
    "forks_count": 1,
    "owner": {"login": "octocat"},
}
USER_REPOS = [
    {
        "full_name": "octocat/spoon-knife",
        "name": "spoon-knife",
        "owner": {"login": "octocat"},
        "private": True,
        "fork": False,
        "archived": False,
        "description": "用来验证 OAuth 导入的仓库",
        "language": "Go",
        "stargazers_count": 3,
        "html_url": "https://github.com/octocat/spoon-knife",
        "updated_at": "2026-11-01T08:00:00Z",
    },
    {
        "full_name": "octocat/hello",
        "name": "hello",
        "owner": {"login": "octocat"},
        "private": False,
        "fork": False,
        "archived": False,
        "description": "已被监控的仓库",
        "language": "Python",
        "stargazers_count": 42,
        "html_url": "https://github.com/octocat/hello",
        "updated_at": "2026-10-20T08:00:00Z",
    },
]


@pytest.fixture(autouse=True)
def oauth_transport():
    seen: list[tuple[str, str, str | None]] = []
    state = {"revoked": False}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        path = request.url.path
        if path == "/login/oauth/access_token":
            if state["revoked"]:
                return httpx.Response(200, json={"error": "bad_verification_code", "error_description": "code 已失效"})
            return httpx.Response(
                200,
                json={"access_token": OAUTH_TOKEN, "token_type": "bearer", "scope": "read:user,repo"},
            )
        if path == "/user":
            if request.headers.get("authorization") != f"Bearer {OAUTH_TOKEN}":
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(200, json=GITHUB_USER, headers={"x-oauth-scopes": "repo, read:user"})
        if path == "/user/repos":
            return httpx.Response(200, json=USER_REPOS)
        if path == "/repos/octocat/spoon-knife":
            return httpx.Response(200, json=REPO_PAYLOAD)
        if path.endswith("/releases"):
            return httpx.Response(200, json=[])
        if path.endswith("/tags"):
            return httpx.Response(200, json=[{"name": "v0.1.0"}])
        return httpx.Response(404, json={"message": "Not Found"})

    set_transport(httpx.MockTransport(handler))
    yield {"seen": seen, "state": state}
    set_transport(None)


def _state_from(location: str) -> str:
    query = parse_qs(urlparse(location).query)
    return query["state"][0]


async def _bind(client: httpx.AsyncClient, headers: dict) -> dict:
    """走完整授权链路：配置 OAuth App → start → callback。"""
    configured = await client.put(
        "/api/github/oauth/app",
        headers=headers,
        json={"client_id": "Iv1.testclientid", "client_secret": "test-client-secret", "scopes": "read:user repo"},
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["configured"] is True
    assert configured.json()["client_id"].startswith("Iv1.")

    start = await client.get("/api/github/oauth/start?next=/github", headers=headers)
    assert start.status_code == 302, start.text
    location = start.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    query = parse_qs(urlparse(location).query)
    assert query["client_id"][0] == "Iv1.testclientid"
    assert "repo" in query["scope"][0]

    callback = await client.get(
        f"/api/github/oauth/callback?code=test-code&state={_state_from(location)}", headers=headers
    )
    assert callback.status_code == 302, callback.text
    assert callback.headers["location"].startswith("/github?")
    assert "github=connected" in callback.headers["location"]
    return {"start": start, "callback": callback}


async def test_oauth_status_before_configuration(client: httpx.AsyncClient, admin_headers: dict):
    status = await client.get("/api/github/oauth/status", headers=admin_headers)
    assert status.status_code == 200
    body = status.json()
    assert body["can_configure"] is True
    assert "redirect_uri" in body
    # 未配置时不能发起授权
    if not body["configured"]:
        start = await client.get("/api/github/oauth/start", headers=admin_headers)
        assert start.status_code == 400


async def test_oauth_bind_and_import(client: httpx.AsyncClient, admin_headers: dict, oauth_transport: dict):
    await _bind(client, admin_headers)

    status = (await client.get("/api/github/oauth/status", headers=admin_headers)).json()
    assert status["configured"] is True
    assert status["connected"] is True
    assert status["account"]["login"] == "octocat"
    assert status["account"]["github_id"] == GITHUB_USER["id"]
    assert "gho_" not in json.dumps(status), "接口不得回显 Token 明文"

    repos = await client.get("/api/github/oauth/repos", headers=admin_headers)
    assert repos.status_code == 200, repos.text
    items = {item["full_name"]: item for item in repos.json()["items"]}
    assert items["octocat/spoon-knife"]["monitored"] is False
    assert items["octocat/spoon-knife"]["private"] is True

    imported = await client.post(
        "/api/github/oauth/import",
        headers=admin_headers,
        json={"full_names": ["octocat/spoon-knife"], "poll_interval_seconds": 600},
    )
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["imported"] == ["octocat/spoon-knife"]
    assert result["failed"] == []

    monitoring = {repo["full_name"]: repo for repo in (await client.get("/api/github/repos", headers=admin_headers)).json()}
    repo = monitoring["octocat/spoon-knife"]
    assert repo["owner_username"] == "admin"
    assert repo["has_token"] is False, "OAuth 导入不应把 Token 复制进仓库记录"

    # 监控检查时才按归属用户动态取用绑定的 Token
    checked = await client.post(f"/api/github/repos/{repo['id']}/check", headers=admin_headers)
    assert checked.status_code == 200, checked.text
    assert checked.json()["ok"] is True
    assert any(
        method == "GET" and path == "/repos/octocat/spoon-knife" and auth == f"Bearer {OAUTH_TOKEN}"
        for method, path, auth in oauth_transport["seen"]
    ), "仓库检查必须使用绑定的 OAuth Token"

    # 重复导入走 skipped 而不是报错
    again = await client.post(
        "/api/github/oauth/import", headers=admin_headers, json={"full_names": ["octocat/spoon-knife"]}
    )
    assert again.json()["skipped"] == ["octocat/spoon-knife"]

    # 导入后列表标记为已监控
    repos = (await client.get("/api/github/oauth/repos", headers=admin_headers)).json()
    assert {item["full_name"]: item for item in repos["items"]}["octocat/spoon-knife"]["monitored"] is True


async def test_oauth_rejects_tampered_state(client: httpx.AsyncClient, admin_headers: dict):
    await _bind(client, admin_headers)
    bad = await client.get("/api/github/oauth/callback?code=test-code&state=forged-state")
    assert bad.status_code == 302
    assert "github=error" in bad.headers["location"]

    missing = await client.get("/api/github/oauth/callback?code=test-code")
    assert missing.status_code == 302
    assert "github=error" in missing.headers["location"]


async def test_oauth_token_exchange_failure_is_reported(client: httpx.AsyncClient, admin_headers: dict, oauth_transport: dict):
    await _bind(client, admin_headers)
    oauth_transport["state"]["revoked"] = True
    start = await client.get("/api/github/oauth/start", headers=admin_headers)
    callback = await client.get(
        f"/api/github/oauth/callback?code=bad-code&state={_state_from(start.headers['location'])}"
    )
    assert callback.status_code == 302
    assert "github=error" in callback.headers["location"]


async def test_repo_isolation_between_users(client: httpx.AsyncClient, admin_headers: dict):
    await _bind(client, admin_headers)
    await client.post("/api/github/oauth/import", headers=admin_headers, json={"full_names": ["octocat/spoon-knife"]})

    roles = (await client.get("/api/roles", headers=admin_headers)).json()
    viewer_role = next(role for role in roles if role["name"] == "viewer")
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "github_viewer",
            "password": "viewer-pass-123456",
            "display_name": "只读访客",
            "role_id": viewer_role["id"],
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post("/api/auth/login", json={"username": "github_viewer", "password": "viewer-pass-123456"})
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    visible = (await client.get("/api/github/repos", headers=viewer_headers)).json()
    assert all(repo["owner_username"] != "admin" for repo in visible), "普通用户不应看到他人在 OAuth 下导入的仓库"

    target = next(
        repo for repo in (await client.get("/api/github/repos", headers=admin_headers)).json()
        if repo["full_name"] == "octocat/spoon-knife"
    )
    denied_view = await client.get(f"/api/github/repos/{target['id']}/releases", headers=viewer_headers)
    assert denied_view.status_code == 403

    status = await client.get("/api/github/oauth/status", headers=viewer_headers)
    assert status.json()["connected"] is False


async def test_disconnect_keeps_repos(client: httpx.AsyncClient, admin_headers: dict):
    await _bind(client, admin_headers)
    await client.post("/api/github/oauth/import", headers=admin_headers, json={"full_names": ["octocat/spoon-knife"]})

    removed = await client.post("/api/github/oauth/disconnect", headers=admin_headers)
    assert removed.status_code == 200, removed.text
    status = (await client.get("/api/github/oauth/status", headers=admin_headers)).json()
    assert status["connected"] is False

    repos = await client.get("/api/github/repos", headers=admin_headers)
    assert any(repo["full_name"] == "octocat/spoon-knife" for repo in repos.json()), "解绑不应删除已监控仓库"

    # 未绑定时不能再拉取仓库列表
    listing = await client.get("/api/github/oauth/repos", headers=admin_headers)
    assert listing.status_code == 400
