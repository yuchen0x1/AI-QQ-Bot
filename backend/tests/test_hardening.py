"""阶段 0 加固回归：迁移互斥、连接绑定任务的队列隔离、可信代理 IP 解析、密码长度。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.security import hash_password, password_needs_rehash, verify_password
from app.db import migrations as migration_module
from app.services.scheduler import CONNECTION_BOUND_TASKS, TASK_HANDLERS


# ---------------------------------------------------------------------------
# 迁移并发
# ---------------------------------------------------------------------------
async def test_concurrent_upgrade_is_serialized(tmp_path) -> None:
    """多个进程同时 upgrade 只能成功建一次 schema，最终版本必须是 head。

    SQLite 没有 advisory lock，这里通过并发调用验证幂等路径不会双写
    alembic_version（PostgreSQL 下由 pg_advisory_xact_lock 串行化）。
    """
    url = f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}"
    results = await asyncio.gather(
        migration_module.upgrade_schema(url),
        migration_module.upgrade_schema(url),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    assert successes, f"至少应有一次升级成功：{results}"
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = list((await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars())
            tables = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
    finally:
        await engine.dispose()
    assert rows == [migration_module.head_revision(migration_module.alembic_config(url))]
    assert "users" in tables


def test_migration_lock_key_is_int64() -> None:
    assert 0 < migration_module.MIGRATION_LOCK_KEY < 2**63


# ---------------------------------------------------------------------------
# 队列任务隔离
# ---------------------------------------------------------------------------
def test_connection_bound_tasks_are_declared() -> None:
    assert CONNECTION_BOUND_TASKS, "必须声明需要机器人连接的任务集合"
    for task_type in ("group_message", "group_announcement", "ai_summary", "online_check"):
        assert task_type in CONNECTION_BOUND_TASKS
    # 每个声明项都必须是真实存在的任务类型，避免拼写错误导致防护失效。
    assert CONNECTION_BOUND_TASKS <= set(TASK_HANDLERS)


def test_pure_local_tasks_can_use_queue() -> None:
    for task_type in ("backup", "clean_expired_data", "health_check"):
        assert task_type not in CONNECTION_BOUND_TASKS


async def test_queue_skips_connection_bound_task(client: httpx.AsyncClient, admin_headers: dict) -> None:
    """调度器不应把需要 adapter 的任务投递给 worker。"""
    from app.db.session import SessionLocal
    from app.models import ScheduledTask
    from app.services.scheduler import scheduler_service

    created = await client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "name": "队列隔离验证",
            "task_type": "group_message",
            "schedule_kind": "interval",
            "interval_seconds": 600,
            "payload": {"account_id": 1, "group_number": 1, "content": "x"},
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    try:
        assert await scheduler_service._task_can_go_to_queue(task_id) is False
    finally:
        async with SessionLocal() as db:
            task = await db.get(ScheduledTask, task_id)
            if task:
                await db.delete(task)
                await db.commit()


# ---------------------------------------------------------------------------
# client_ip 与可信代理
# ---------------------------------------------------------------------------
def test_client_ip_ignores_forwarded_header_from_untrusted_peer() -> None:
    from app.api.deps import client_ip

    class _Client:
        host = "203.0.113.9"  # 公网地址，不在 TRUSTED_PROXIES 内

    class _Req:
        client = _Client()
        headers = {"x-forwarded-for": "1.2.3.4"}

    assert client_ip(_Req()) == "203.0.113.9"


def test_client_ip_uses_forwarded_header_from_trusted_proxy() -> None:
    from app.api.deps import client_ip

    class _Client:
        host = "172.18.0.5"  # Docker 内部网段，属于默认可信代理

    class _Req:
        client = _Client()
        headers = {"x-forwarded-for": "198.51.100.7, 172.18.0.5"}

    assert client_ip(_Req()) == "198.51.100.7"


def test_is_trusted_proxy_handles_invalid_input() -> None:
    assert settings.is_trusted_proxy("172.18.0.5") is True
    assert settings.is_trusted_proxy("203.0.113.9") is False
    assert settings.is_trusted_proxy("not-an-ip") is False
    assert settings.is_trusted_proxy(None) is False


# ---------------------------------------------------------------------------
# 密码长度
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "password",
    ["a" * 72, "a" * 200, "密" * 30, "密" * 100, "admin123"],
    ids=["ascii-72", "ascii-200", "cjk-30", "cjk-100", "short"],
)
def test_long_passwords_hash_and_verify(password: str) -> None:
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password(password + "x", hashed) is False


def test_new_hashes_are_marked_for_versioned_scheme() -> None:
    hashed = hash_password("whatever-password")
    assert password_needs_rehash(hashed) is False


def test_legacy_bcrypt_hash_still_verifies() -> None:
    """升级前写入的历史哈希（无 sha256: 前缀）必须仍可登录。"""
    import bcrypt

    legacy = bcrypt.hashpw(b"admin123", bcrypt.gensalt(rounds=4)).decode()
    assert password_needs_rehash(legacy) is True
    assert verify_password("admin123", legacy) is True


def test_legacy_long_password_is_truncated_not_rejected() -> None:
    """老库里超 72 字节的密码，bcrypt 5.x 会抛错；这里必须显式截断后比对。"""
    import bcrypt

    raw = ("密" * 30).encode("utf-8")[:72]
    legacy = bcrypt.hashpw(raw, bcrypt.gensalt(rounds=4)).decode()
    assert verify_password("密" * 30, legacy) is True


# ---------------------------------------------------------------------------
# 分页上界
# ---------------------------------------------------------------------------
async def test_page_size_upper_bound_is_enforced(client: httpx.AsyncClient, admin_headers: dict) -> None:
    resp = await client.get("/api/logs?page_size=100000", headers=admin_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WebSocket 票据
# ---------------------------------------------------------------------------
async def test_ws_ticket_replaces_long_lived_token(client: httpx.AsyncClient, admin_headers: dict) -> None:
    resp = await client.post("/api/ws/ticket", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expires_in"] == 60
    ticket = body["ticket"]

    from app.core.security import decode_access_token

    payload = decode_access_token(ticket)
    assert payload is not None
    assert payload["purpose"] == "ws_ticket"
    assert payload["session_jti"], "票据必须绑定原会话，撤销后长连接才能失效"
    # 票据不能当作普通 API 凭证使用
    bad = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {ticket}"})
    assert bad.status_code == 401


async def test_ws_ticket_requires_login(client: httpx.AsyncClient) -> None:
    # 共享 client 会保留登录 cookie，这里显式清空以模拟真正的未登录请求。
    resp = await client.post("/api/ws/ticket", headers={"Cookie": ""})
    assert resp.status_code == 401
