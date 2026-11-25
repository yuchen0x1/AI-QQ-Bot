"""AI request boundaries and nullable-scope concurrency regressions."""

from __future__ import annotations

import asyncio
import json
import socket
import uuid

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.http import PinnedAddressTransport, set_transport
from app.core.ssrf import OutboundTarget, OutboundURLError, resolve_outbound_target, validate_outbound_base_url
from app.db import migrations
from app.db.session import SessionLocal
from app.models import Account, AIConversation, AIMessage, AIModel, AIProvider, Group, Message
from app.services.ai import service
from app.services.ai.providers import AIError, ChatResult, build_provider


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    set_transport(None)


async def _model_pair(db, *, cross_provider=False):
    marker = uuid.uuid4().hex[:12]
    provider = AIProvider(name=f"safety-{marker}", kind="custom", base_url="https://models.example.test/v1")
    other = AIProvider(name=f"safety-other-{marker}", kind="custom", base_url="https://other.example.test/v1")
    primary = AIModel(provider=provider, model_name=f"primary-{marker}", retries=0,
                      allow_cross_provider_fallback=cross_provider)
    backup = AIModel(provider=other, model_name=f"backup-{marker}", retries=0, is_fallback=True)
    db.add_all([primary, backup])
    await db.commit()
    return primary, backup


@pytest.mark.parametrize("status", [302, 307, 308])
@pytest.mark.parametrize("method", ["get", "post"])
async def test_ai_redirect_never_sends_credentials_to_another_target(status, method):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={"Location": "http://169.254.169.254/latest/meta-data"})

    set_transport(httpx.MockTransport(handler))
    provider = build_provider("custom", base_url="https://models.example.test/v1", api_key="credential-only-public", model_name="test")
    with pytest.raises(AIError, match="重定向"):
        if method == "get":
            await provider.list_models()
        else:
            await provider.chat([{"role": "user", "content": "hello"}])
    assert len(seen) == 1
    assert seen[0].url.host == "models.example.test"
    assert seen[0].headers["Authorization"] == "Bearer credential-only-public"


async def test_ai_revalidates_dns_at_send_after_configuration(monkeypatch):
    validate_outbound_base_url("https://models.example.test/v1")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    seen = []
    set_transport(httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json={})))
    provider = build_provider("custom", base_url="https://models.example.test/v1", api_key="secret", model_name="test")
    with pytest.raises(AIError, match="安全策略"):
        await provider.chat([{"role": "user", "content": "hello"}])
    assert seen == []


@pytest.mark.parametrize("address", ["::ffff:127.0.0.1", "::1", "169.254.169.254", "100.100.100.200", "fd00::1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::"])
def test_provider_ip_policy_covers_ipv6_and_metadata(address):
    host = f"[{address}]" if ":" in address else address
    with pytest.raises(OutboundURLError):
        resolve_outbound_target(f"https://{host}/v1")


def test_mixed_dns_answers_reject_private_ipv6(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0)),
    ])
    with pytest.raises(OutboundURLError):
        resolve_outbound_target("https://mixed.example.test/v1")


@pytest.mark.parametrize("address", ["100.100.100.200", "100.64.0.1", "192.0.2.1", "2001:db8::1", "::ffff:100.100.100.200"])
def test_ollama_allowlist_does_not_authorize_metadata_or_reserved_addresses(address):
    host = f"[{address}]" if ":" in address else address
    endpoint = f"http://{host}:11434"
    with pytest.raises(OutboundURLError):
        resolve_outbound_target(endpoint, allow_http=True, private_allowlist=[endpoint])


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "172.16.1.2", "192.168.1.2", "::1", "fd00::1"])
def test_ollama_allowlist_preserves_explicit_local_model_networks(address):
    host = f"[{address}]" if ":" in address else address
    endpoint = f"http://{host}:11434"
    assert resolve_outbound_target(endpoint, allow_http=True, private_allowlist=[endpoint]).addresses == (address,)


async def test_production_transport_pins_dns_and_preserves_tls_identity():
    seen = []
    target = OutboundTarget("https://models.example.test/v1", "models.example.test", ("8.8.8.8",))
    transport = PinnedAddressTransport(target, httpx.MockTransport(
        lambda request: seen.append(request) or httpx.Response(200, json={"ok": True})
    ))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(target.url)
    assert response.status_code == 200
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["Host"] == "models.example.test"
    assert seen[0].extensions["sni_hostname"] == "models.example.test"


async def test_ollama_requires_exact_admin_endpoint_allowlist(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "ollama_allowed_base_urls", ["http://127.0.0.1:11434"])
    response = await client.post("/api/ai/providers", headers=admin_headers, json={
        "name": f"local-{uuid.uuid4().hex}", "kind": "ollama", "base_url": "http://127.0.0.1:11434",
    })
    assert response.status_code == 201, response.text
    denied = await client.post("/api/ai/providers", headers=admin_headers, json={
        "name": f"local-denied-{uuid.uuid4().hex}", "kind": "ollama", "base_url": "http://127.0.0.1:11435",
    })
    assert denied.status_code == 400
    set_transport(httpx.MockTransport(lambda request: httpx.Response(200, json={"message": {"content": "local"}})))
    provider = build_provider("ollama", base_url="http://127.0.0.1:11434", api_key=None, model_name="test")
    assert (await provider.chat([{"role": "user", "content": "hello"}])).content == "local"
    monkeypatch.setattr(settings, "ollama_allowed_base_urls", [])
    with pytest.raises(AIError, match="安全策略"):
        await provider.chat([{"role": "user", "content": "hello"}])


async def test_unmarked_fallback_gets_zero_calls(client, db):
    primary, backup = await _model_pair(db, cross_provider=True)
    backup.is_fallback = False
    await db.commit()
    called = []

    def handler(request):
        called.append(json.loads(request.content)["model"])
        return httpx.Response(503, json={"error": "down"})

    set_transport(httpx.MockTransport(handler))
    result, error, _ = await service.chat_once(db, primary, [{"role": "user", "content": "private"}])
    assert result is None and error
    assert primary.model_name in called
    assert backup.model_name not in called


async def test_cross_provider_fallback_is_opt_in_and_can_be_disabled_by_account(client, db):
    primary, backup = await _model_pair(db)
    assert backup.id not in {m.id for m in await service.fallback_models(db, primary.id)}
    primary.allow_cross_provider_fallback = True
    await db.commit()
    assert backup.id in {m.id for m in await service.fallback_models(db, primary.id)}
    account = Account(account_id=uuid.uuid4().hex, name="fallback-scope", enabled=False, features={"ai_allow_cross_provider_fallback": False})
    db.add(account)
    await db.commit()
    assert backup.id not in {m.id for m in await service.fallback_models(db, primary.id, account_id=account.id)}


async def test_fallback_and_primary_respect_account_and_group_allowlists(client, db):
    primary, backup = await _model_pair(db, cross_provider=True)
    account = Account(account_id=uuid.uuid4().hex, name="model-scope", enabled=False, features={
        "ai_allowed_model_ids": [primary.id, backup.id], "ai_group_model_ids": {"9001": [primary.id]},
    })
    db.add(account)
    await db.commit()
    assert await service.resolve_model(db, model_id=backup.id, account_id=account.id, group_number=9001) is None
    candidates = await service.fallback_models(db, primary.id, account_id=account.id, group_number=9001)
    assert candidates == []
    assert (await service.resolve_model(db, model_id=primary.id, account_id=account.id, group_number=9001)).id == primary.id


async def test_scheduled_summary_preserves_model_scope_during_fallback(client, db):
    from app.services.scheduler import _task_ai_summary

    primary, _ = await _model_pair(db, cross_provider=True)
    group_number = 445001
    account = Account(account_id=uuid.uuid4().hex, name="summary-model-scope", enabled=False, features={
        "ai_model_id": primary.id, "ai_allowed_model_ids": [primary.id],
        "ai_group_model_ids": {str(group_number): [primary.id]},
    })
    db.add(account)
    await db.flush()
    db.add_all([
        Group(account_id=account.id, group_number=group_number, name="restricted summary"),
        Message(account_id=account.id, qq_group=group_number, direction="in", message_type="group",
                sender_name="member", content="private summary transcript"),
    ])
    await db.commit()
    called = []

    def handler(request):
        model_name = json.loads(request.content)["model"]
        called.append(model_name)
        if model_name == primary.model_name:
            return httpx.Response(503, json={"error": "primary unavailable"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "unauthorized summary"}}]})

    set_transport(httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="AI 总结失败"):
        await _task_ai_summary({"account_id": account.id, "group_number": group_number, "send_to_group": False})
    assert called == [primary.model_name]


async def test_whole_call_deadline_cancels_actual_upstream(client, db, monkeypatch):
    primary, _ = await _model_pair(db)
    cancelled = asyncio.Event()

    class SlowProvider:
        async def chat(self, messages, system=None):
            try:
                await asyncio.sleep(10)
                return ChatResult(content="too late")
            finally:
                cancelled.set()

    monkeypatch.setattr(service, "provider_to_client", lambda *a, **k: SlowProvider())
    monkeypatch.setattr(settings, "ai_call_deadline_seconds", 0.03)
    result, error, _ = await service.chat_once(db, primary, [{"role": "user", "content": "hello"}])
    assert result is None and "整次" in error
    assert cancelled.is_set()


async def test_external_cancellation_does_not_start_fallback(client, db, monkeypatch):
    primary, _ = await _model_pair(db, cross_provider=True)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []

    class SlowProvider:
        async def chat(self, messages, system=None):
            entered.set()
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

    monkeypatch.setattr(service, "provider_to_client", lambda model, **kw: calls.append(model.id) or SlowProvider())
    task = asyncio.create_task(service.chat_once(db, primary, [{"role": "user", "content": "hello"}]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set() and calls == [primary.id]


async def test_nullable_scope_concurrent_creation_returns_one_conversation(client, db):
    account = Account(account_id=uuid.uuid4().hex, name="conversation-race", enabled=False)
    db.add(account)
    await db.commit()

    async def create():
        async with SessionLocal() as session:
            result = await service.get_or_create_conversation(session, account_id=account.id, scope="group", group_number=123)
            return result.id

    ids = await asyncio.gather(*(create() for _ in range(5)))
    assert len(set(ids)) == 1
    count = await db.scalar(select(func.count()).select_from(AIConversation).where(AIConversation.account_id == account.id))
    assert count == 1


async def test_scope_migration_preserves_duplicate_messages(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'duplicate-scopes.db').as_posix()}"
    await asyncio.to_thread(command.upgrade, migrations.alembic_config(url), "0016_repository_oauth_scope")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("""INSERT INTO accounts
                (id,account_id,name,protocol,connection_mode,enabled,auto_start,auto_reconnect,reconnect_base_seconds,reconnect_max_seconds,features)
                VALUES (1,'scope-migrate','scope-migrate','qq_official','official_ws',1,0,1,5,300,'{}')"""))
            await conn.execute(sa.text("""INSERT INTO ai_conversations
                (id,account_id,scope,group_number,user_id,message_count)
                VALUES (1,1,'group',123,NULL,1),(2,1,'group',123,NULL,1)"""))
            await conn.execute(sa.text("""INSERT INTO ai_messages
                (conversation_id,role,content,tokens,created_at)
                VALUES (1,'user','first',0,CURRENT_TIMESTAMP),(2,'assistant','second',0,CURRENT_TIMESTAMP)"""))
        await asyncio.to_thread(command.upgrade, migrations.alembic_config(url), "0017_ai_scope_key")
        async with engine.connect() as conn:
            rows = (await conn.execute(sa.text("SELECT id,scope_key,message_count FROM ai_conversations"))).all()
            assert rows == [(1, "group:123:-", 2)]
            messages = (await conn.execute(sa.select(AIMessage.content, AIMessage.conversation_id).order_by(AIMessage.id))).all()
            assert messages == [("first", 1), ("second", 1)]
    finally:
        await engine.dispose()


async def test_scope_migration_resumes_after_partial_add_column(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'interrupted-scope.db').as_posix()}"
    await asyncio.to_thread(command.upgrade, migrations.alembic_config(url), "0016_repository_oauth_scope")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE ai_models ADD COLUMN allow_cross_provider_fallback BOOLEAN NOT NULL DEFAULT FALSE"))
            await conn.execute(sa.text("ALTER TABLE ai_conversations ADD COLUMN scope_key VARCHAR(96)"))
        await asyncio.to_thread(command.upgrade, migrations.alembic_config(url), "0017_ai_scope_key")
        async with engine.connect() as conn:
            constraints, columns = await conn.run_sync(lambda connection: (
                sa.inspect(connection).get_unique_constraints("ai_conversations"),
                sa.inspect(connection).get_columns("ai_conversations"),
            ))
        assert any(item["name"] == "uq_conversation_scope_key" for item in constraints)
        assert next(item for item in columns if item["name"] == "scope_key")["nullable"] is False
    finally:
        await engine.dispose()
