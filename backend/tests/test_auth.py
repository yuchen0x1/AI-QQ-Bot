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
