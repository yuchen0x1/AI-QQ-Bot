"""测试夹具：使用独立 SQLite 数据库 + ASGI 直连客户端，不依赖任何外部服务。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 必须在导入 app 之前设置环境变量
_TMP = Path(tempfile.mkdtemp(prefix="qbot-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "unit-test-secret-key-please-ignore-0123456789"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["BACKUP_DIR"] = str(_TMP / "backups")
os.environ["PLUGIN_DIR"] = str(Path(__file__).resolve().parents[1] / "plugins")
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["REDIS_ENABLED"] = "false"

import httpx  # noqa: E402

from app.main import app  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.services.account_manager import account_manager  # noqa: E402


@pytest.fixture(scope="session")
async def client():
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
                yield async_client
    finally:
        # Explicitly close pooled aiosqlite connections before the session event loop exits.
        await engine.dispose()


@pytest.fixture(scope="session")
async def admin_headers(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def db():
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def mock_account(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    """创建一个模拟协议账号并启动，测试结束后停止并删除。"""
    response = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json={
            "name": "测试模拟账号",
            "protocol": "mock",
            "connection_mode": "http",
            "qq_number": 100001,
            "auto_reconnect": False,
            "enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    account = response.json()
    start = await client.post(f"/api/accounts/{account['id']}/start", headers=admin_headers)
    assert start.status_code == 200, start.text
    for _ in range(50):
        if account_manager.is_online(account["id"]):
            break
        import asyncio

        await asyncio.sleep(0.1)
    assert account_manager.is_online(account["id"]), "模拟账号未能上线"
    yield account
    await client.delete(f"/api/accounts/{account['id']}", headers=admin_headers)
