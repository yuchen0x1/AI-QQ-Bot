"""认证与 RBAC 测试。"""

from __future__ import annotations

import httpx

from app.core.config import settings


async def test_login_success(client: httpx.AsyncClient):
    response = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["role"]["name"] == "super_admin"


async def test_login_wrong_password(client: httpx.AsyncClient):
    response = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 401
    assert "用户名或密码错误" in response.json()["detail"]


async def test_requires_token(client: httpx.AsyncClient):
    client.cookies.clear()  # 避免复用登录写入的 Cookie
    response = await client.get("/api/accounts")
    assert response.status_code == 401


async def test_invalid_token(client: httpx.AsyncClient):
    response = await client.get("/api/accounts", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


async def test_rbac_viewer_cannot_manage(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    roles = (await client.get("/api/roles", headers=admin_headers)).json()
    viewer_role = next(r for r in roles if r["name"] == "viewer")
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "viewer_user", "password": "Viewer@12345", "role_id": viewer_role["id"]},
    )
    assert created.status_code in (201, 409), created.text
    login = await client.post("/api/auth/login", json={"username": "viewer_user", "password": "Viewer@12345"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 只读角色可以看账号列表
    assert (await client.get("/api/accounts", headers=headers)).status_code == 200
    # 但不能创建账号
    resp = await client.post("/api/accounts", headers=headers, json={"name": "非法账号", "protocol": "mock"})
    assert resp.status_code == 403
    # 也不能访问用户管理
    assert (await client.get("/api/users", headers=headers)).status_code == 403


async def test_login_lockout(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    roles = (await client.get("/api/roles", headers=admin_headers)).json()
    viewer_role = next(r for r in roles if r["name"] == "viewer")
    await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "lock_target", "password": "Lock@12345", "role_id": viewer_role["id"]},
    )
    for _ in range(settings.login_max_attempts):
        resp = await client.post("/api/auth/login", json={"username": "lock_target", "password": "bad"})
        assert resp.status_code == 401
    locked = await client.post("/api/auth/login", json={"username": "lock_target", "password": "Lock@12345"})
    assert locked.status_code == 423
    assert "锁定" in locked.json()["detail"]


async def test_change_password(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "pwd_user", "password": "Old@12345"},
    )
    login = await client.post("/api/auth/login", json={"username": "pwd_user", "password": "Old@12345"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    bad = await client.post(
        "/api/auth/password", headers=headers, json={"old_password": "wrong", "new_password": "New@123456"}
    )
    assert bad.status_code == 400
    ok = await client.post(
        "/api/auth/password", headers=headers, json={"old_password": "Old@12345", "new_password": "New@123456"}
    )
    assert ok.status_code == 200
    assert (await client.post("/api/auth/login", json={"username": "pwd_user", "password": "New@123456"})).status_code == 200


async def test_old_token_revoked_after_password_change(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    """修改密码后，改密前签发的 JWT 必须立即失效。"""
    await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "revoke_user", "password": "Old@12345"},
    )
    login = await client.post("/api/auth/login", json={"username": "revoke_user", "password": "Old@12345"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200

    changed = await client.post(
        "/api/auth/password", headers=headers, json={"old_password": "Old@12345", "new_password": "New@123456"}
    )
    assert changed.status_code == 200

    client.cookies.clear()  # 确保只携带旧 Bearer Token
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401


async def test_admin_reset_password_revokes_user_tokens(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    """管理员重置用户密码后，该用户旧 Token 必须失效。"""
    await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "reset_user", "password": "Old@12345"},
    )
    login = await client.post("/api/auth/login", json={"username": "reset_user", "password": "Old@12345"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    users = (await client.get("/api/users", headers=admin_headers, params={"keyword": "reset_user"})).json()
    target = next(u for u in users["items"] if u["username"] == "reset_user")

    client.cookies.clear()
    resp = await client.put(f"/api/users/{target['id']}", headers=admin_headers, json={"password": "Reset@123456"})
    assert resp.status_code == 200
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401


async def test_totp_login_and_session_revocation(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "totp_user", "password": "Totp@12345"},
    )
    assert created.status_code in (201, 409), created.text

    login = await client.post("/api/auth/login", json={"username": "totp_user", "password": "Totp@12345"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    setup = await client.post("/api/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    from app.core.totp import generate_code

    confirm = await client.post("/api/auth/2fa/confirm", headers=headers, json={"code": generate_code(secret)})
    assert confirm.status_code == 200

    client.cookies.clear()
    two_factor_login = await client.post("/api/auth/login", json={"username": "totp_user", "password": "Totp@12345"})
    assert two_factor_login.status_code == 200
    challenge = two_factor_login.json()
    assert challenge["requires_2fa"] is True
    assert challenge["access_token"] is None

    verified = await client.post(
        "/api/auth/login/2fa",
        json={"challenge_token": challenge["challenge_token"], "code": generate_code(secret)},
    )
    assert verified.status_code == 200
    token = verified.json()["access_token"]
    session_headers = {"Authorization": f"Bearer {token}"}
    sessions = await client.get("/api/auth/sessions", headers=session_headers)
    assert sessions.status_code == 200
    current = next(item for item in sessions.json() if item["current"])

    replay = await client.post(
        "/api/auth/login/2fa",
        json={"challenge_token": challenge["challenge_token"], "code": generate_code(secret)},
    )
    assert replay.status_code == 401
    assert (await client.delete(f"/api/auth/sessions/{current['id']}", headers=session_headers)).status_code == 400

    logout = await client.post("/api/auth/logout", headers=session_headers)
    assert logout.status_code == 200
    assert (await client.get("/api/auth/me", headers=session_headers)).status_code == 401
