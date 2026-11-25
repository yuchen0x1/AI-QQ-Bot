"""Exercise populated v1.5.3 schemas on SQLite and opt-in disposable PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from uuid import uuid4

from alembic import command
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.security import decrypt_secret, encrypt_secret
from app.db.migrations import alembic_config, upgrade_schema


@pytest.fixture(params=["sqlite", "postgresql"])
async def upgrade_database(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}"
        return
    configured = os.environ.get("TEST_POSTGRES_URL")
    if not configured:
        pytest.skip("TEST_POSTGRES_URL not set: live PostgreSQL migration NOT RUN")
    database = "qbot_upgrade_test_" + uuid4().hex
    admin = create_async_engine(configured, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'CREATE DATABASE "{database}"'))
        yield make_url(configured).set(database=database).render_as_string(hide_password=False)
    finally:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin.dispose()


async def _legacy_fixture(database_url):
    config = alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, "0015_ws_tickets")
    engine = create_async_engine(database_url)
    now = datetime.now(timezone.utc)
    secret = encrypt_secret("fixture-secret-preserved-through-migration")
    try:
        async with engine.begin() as conn:
            metadata = sa.MetaData()
            await conn.run_sync(metadata.reflect)

            async def insert(table, values):
                result = await conn.execute(metadata.tables[table].insert().values(**values))
                return result.inserted_primary_key[0]

            account_id = await insert("accounts", dict(
                account_id="upgrade-official", name="升级保留账号", protocol="qq_official",
                connection_mode="official_webhook", enabled=True, auto_start=False, auto_reconnect=True,
                reconnect_base_seconds=5, reconnect_max_seconds=300, features={"ai_enabled": True},
                app_id="upgrade-fixture-app", app_secret_enc=secret))
            user_id = await insert("users", dict(username="upgrade-owner", password_hash="fixture-hash",
                                                is_active=True, failed_attempts=0, totp_enabled=False))
            provider = await insert("ai_providers", dict(name="upgrade-provider", kind="openai",
                                                       base_url="https://api.example.com", api_key_enc=secret,
                                                       enabled=True, extra_headers={}))
            model = await insert("ai_models", dict(provider_id=provider, model_name="upgrade-model",
                temperature=0.7, max_tokens=2048, timeout_seconds=30, retries=1, priority=100,
                is_default=True, is_fallback=False, enabled=True, total_calls=2, total_errors=0, total_tokens=4))
            repository = await insert("github_repositories", dict(provider="github", owner="fixture",
                name="upgrade", full_name="fixture/upgrade", html_url="https://github.com/fixture/upgrade",
                stars=1, forks=0, owner_user_id=user_id, token_enc=secret, monitor_enabled=True,
                remote_available=True, poll_interval_seconds=900, notify_prerelease=False,
                monitor_activity=True))
            rule = await insert("push_rules", dict(repository_id=repository, account_id=account_id,
                qq_group=912345, enabled=True, only_stable=True, include_changelog=True,
                include_downloads=True, ai_summary=False, markdown_card=True, mention_user_ids=[],
                event_types=["release"], managed_by_user_id=user_id, total_pushed=3))
            await insert("scheduled_tasks", dict(name="upgrade-task", task_type="group_message",
                schedule_kind="interval", interval_seconds=3600, payload={"account_id": account_id,
                "group_number": 912345, "message": "preserved"}, enabled=False, max_retries=2,
                timeout_seconds=30, total_runs=4, total_failures=1, job_key="upgrade-task"))
            plugin = await insert("plugins", dict(plugin_id="upgrade-custom", name="Custom preserved",
                version="1.0.0", permissions=["message:reply"], config={"reply": "preserved"}, enabled=False,
                builtin=False, path="/var/lib/qbot/extensions/upgrade-custom", commands=["/custom"]))
            await insert("plugin_bindings", dict(plugin_id=plugin, scope="account", target_id=str(account_id), enabled=True))
            await insert("system_settings", dict(key="upgrade-encrypted", value={"value": secret}, is_secret=True))
            for index in range(2):
                conversation = await insert("ai_conversations", dict(account_id=account_id, scope="group",
                    group_number=912345, user_id=None, model_id=model, message_count=1,
                    system_prompt="preserved prompt", last_active_at=now))
                await insert("ai_messages", dict(conversation_id=conversation, role="user",
                    content=f"历史消息 {index}", tokens=2, created_at=now))
        return account_id, user_id, model, repository, rule
    finally:
        await engine.dispose()


async def test_populated_v153_upgrade_preserves_scopes_keys_rules_plugins_and_history(upgrade_database):
    account, owner, model, repository, rule = await _legacy_fixture(upgrade_database)
    await upgrade_schema(upgrade_database)
    engine = create_async_engine(upgrade_database)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT * FROM accounts WHERE id=:id"), {"id": account})).mappings().one()
            assert row["name"] == "升级保留账号" and row["enabled"]
            assert decrypt_secret(row["app_secret_enc"]) == "fixture-secret-preserved-through-migration"
            row = (await conn.execute(sa.text("SELECT * FROM github_repositories WHERE id=:id"), {"id": repository})).mappings().one()
            assert row["owner_user_id"] == owner and row["archived_at"] is None and row["monitor_enabled"]
            assert decrypt_secret(row["token_enc"]) == "fixture-secret-preserved-through-migration"
            assert (await conn.execute(sa.text("SELECT total_pushed FROM push_rules WHERE id=:id"), {"id": rule})).scalar_one() == 3
            assert (await conn.execute(sa.text("SELECT count(*) FROM plugin_bindings"))).scalar_one() == 1
            assert (await conn.execute(sa.text("SELECT job_key FROM scheduled_tasks"))).scalar_one() == "upgrade-task"
            assert not (await conn.execute(sa.text("SELECT allow_cross_provider_fallback FROM ai_models WHERE id=:id"), {"id": model})).scalar_one()
            conversations = (await conn.execute(sa.text("SELECT scope_key,message_count FROM ai_conversations"))).all()
            assert conversations == [("group:912345:-", 2)]
            assert (await conn.execute(sa.text("SELECT content FROM ai_messages ORDER BY id"))).scalars().all() == ["历史消息 0", "历史消息 1"]
        # The migrated schema can accept new data under the new constraints.
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE plugins SET enabled=:enabled WHERE plugin_id='upgrade-custom'"), {"enabled": True})
        await asyncio.to_thread(command.check, alembic_config(upgrade_database))
        assert await upgrade_schema(upgrade_database)
    finally:
        await engine.dispose()
