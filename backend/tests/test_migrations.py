"""Alembic schema 管理测试：全部使用临时 SQLite，不触碰任何真实数据库。"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.permissions import ROLE_DEFS
from app.db import migrations as migration_module
from app.db.init_db import seed
from app.db.migrations import SchemaVersionError
from app.db.session import SessionLocal
from app.models import Base, BotCommand, Plugin, Role, SystemSetting, User

HEAD = "0006_auth_security"


@pytest.fixture
def database_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'migrate.db').as_posix()}"


async def _upgrade_to(database_url: str, revision: str) -> None:
    config = migration_module.alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, revision)


async def _schema_snapshot(database_url: str, table: str) -> tuple[set[str], set[str]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            tables = set(await conn.run_sync(lambda sync_conn: sa.inspect(sync_conn).get_table_names()))
            columns = set(await conn.run_sync(lambda sync_conn: [c["name"] for c in sa.inspect(sync_conn).get_columns(table)]))
            return tables, columns
    finally:
        await engine.dispose()


async def _version(database_url: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            rows = list((await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars())
            return str(rows[0])
    finally:
        await engine.dispose()


async def _seed_counts() -> tuple[int, int, int, int, int]:
    async with SessionLocal() as session:
        roles = await session.scalar(select(func.count()).select_from(Role))
        users = await session.scalar(select(func.count()).select_from(User))
        settings = await session.scalar(select(func.count()).select_from(SystemSetting))
        commands = await session.scalar(select(func.count()).select_from(BotCommand))
        plugins = await session.scalar(select(func.count()).select_from(Plugin))
    return roles or 0, users or 0, settings or 0, commands or 0, plugins or 0


async def test_fresh_database_upgrades_to_head(database_url: str) -> None:
    assert await migration_module.upgrade_schema(database_url) == HEAD
    tables, columns = await _schema_snapshot(database_url, "account_connections")
    assert {"accounts", "users", "bot_requests", "scheduled_tasks", "alembic_version"} <= tables
    assert {"lease_owner", "lease_id", "lease_expires_at"} <= columns
    assert "qq_official_identities" in tables
    _, account_columns = await _schema_snapshot(database_url, "accounts")
    assert {"app_id", "app_secret_enc", "bot_openid"} <= account_columns
    assert "user_github_tokens" in tables
    _, repo_columns = await _schema_snapshot(database_url, "github_repositories")
    assert "owner_user_id" in repo_columns
    assert await _version(database_url) == HEAD


async def test_repeated_upgrade_is_idempotent(database_url: str) -> None:
    await migration_module.upgrade_schema(database_url)
    assert await migration_module.upgrade_schema(database_url) == HEAD
    assert await _version(database_url) == HEAD


async def test_migrated_schema_matches_models(database_url: str) -> None:
    await migration_module.upgrade_schema(database_url)
    config = migration_module.alembic_config(database_url)
    await asyncio.to_thread(command.check, config)


async def test_seed_is_idempotent() -> None:
    await migration_module.upgrade_schema()
    await seed()
    first = await _seed_counts()
    await seed()
    second = await _seed_counts()
    assert first == second
    assert first[0] == len(ROLE_DEFS)
    assert first[1] >= 1


async def test_database_behind_head_is_upgraded(database_url: str) -> None:
    await _upgrade_to(database_url, "0001_initial")
    tables, columns = await _schema_snapshot(database_url, "account_connections")
    assert "bot_requests" not in tables
    assert "lease_owner" not in columns

    assert await migration_module.upgrade_schema(database_url) == HEAD
    tables, columns = await _schema_snapshot(database_url, "account_connections")
    assert "bot_requests" in tables
    assert {"lease_owner", "lease_id", "lease_expires_at"} <= columns
    assert await _version(database_url) == HEAD


async def test_unknown_revision_is_rejected(database_url: str) -> None:
    await migration_module.upgrade_schema(database_url)
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE alembic_version SET version_num = '9999_unknown'"))
    finally:
        await engine.dispose()
    with pytest.raises(SchemaVersionError, match="不在当前迁移链中"):
        await migration_module.upgrade_schema(database_url)


async def test_legacy_database_without_version_is_rejected(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
    with pytest.raises(SchemaVersionError, match="未纳入 Alembic 版本管理"):
        await migration_module.upgrade_schema(database_url)
