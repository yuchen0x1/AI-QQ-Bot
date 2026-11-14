"""插件运行指标与权限审计测试。"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import Plugin
from app.services.plugins import plugin_manager

PLUGIN_ID = "metrics-demo"


def _write_test_plugin(tmp_path) -> str:
    root = tmp_path / PLUGIN_ID
    root.mkdir()
    (root / "main.py").write_text(
        "async def ping(message):\n"
        "    return 'pong'\n"
        "\n"
        "async def boom(message):\n"
        "    raise ValueError('demo failure')\n"
        "\n"
        "async def hook(message):\n"
        "    ctx_ok = message.text.startswith('/ai')\n"
        "    return None\n"
        "\n"
        "def register(ctx):\n"
        "    ctx.add_command('ping', ping)\n"
        "    ctx.add_command('boom', boom)\n"
        "    ctx.on_message(hook)\n"
        "    async def probe(message):\n"
        "        ctx.has_permission('ai:request')\n"
        "        ctx.has_permission('http:request')\n"
        "        return None\n"
        "    ctx.message_hooks.append(probe)\n",
        encoding="utf-8",
    )
    return str(root)


@pytest.fixture
async def loaded_plugin(client: httpx.AsyncClient, db: AsyncSession, tmp_path):
    path = _write_test_plugin(tmp_path)
    plugin = Plugin(
        plugin_id=PLUGIN_ID,
        name="指标演示",
        version="1.0.0",
        permissions=["message:reply", "ai:request"],
        config={},
        enabled=True,
        builtin=False,
        path=path,
        commands=["ping", "boom"],
    )
    db.add(plugin)
    await db.commit()
    await db.refresh(plugin)
    loaded = plugin_manager.load_one(plugin)
    assert loaded is not None
    yield plugin
    plugin_manager.loaded.pop(PLUGIN_ID, None)
    plugin_manager.metrics.pop(PLUGIN_ID, None)
    plugin_manager.permission_audit_log.clear()
    await db.delete(plugin)
    await db.commit()


async def _dispatch(db: AsyncSession, plugin: Plugin, text: str) -> list[str]:
    return await plugin_manager.dispatch_message(
        db,
        account_id=1,
        group_number=10086,
        user_id=42,
        text=text,
        sender_name="tester",
    )


@pytest.mark.asyncio
async def test_plugin_metrics_track_duration_and_errors(db: AsyncSession, loaded_plugin: Plugin):
    ok = await _dispatch(db, loaded_plugin, "/ping")
    assert ok == ["pong"]
    bad = await _dispatch(db, loaded_plugin, "/boom")
    assert any("执行出错" in r for r in bad)

    metrics = plugin_manager.metrics_for(PLUGIN_ID)
    assert metrics.invocations == 2
    assert metrics.errors == 1
    assert metrics.error_rate == 0.5
    assert metrics.last_duration_ms is not None and metrics.last_duration_ms >= 0
    assert metrics.last_error and "ValueError" in metrics.last_error
    assert metrics.last_run_at


@pytest.mark.asyncio
async def test_permission_checks_are_audited(db: AsyncSession, loaded_plugin: Plugin):
    await _dispatch(db, loaded_plugin, "/ping")  # 命中命令，钩子不执行；分发器的 message:reply 门控仍会计入审计

    await _dispatch(db, loaded_plugin, "/普通消息")  # 未命中命令，消息钩子执行权限探测

    checks = [e for e in plugin_manager.permission_audit_log if e["plugin_id"] == PLUGIN_ID]
    by_permission = {e["permission"]: e for e in checks}
    assert by_permission["message:reply"]["allowed"] is True
    assert by_permission["ai:request"]["allowed"] is True
    assert by_permission["http:request"]["allowed"] is False
    metrics = plugin_manager.metrics_for(PLUGIN_ID)
    assert metrics.permission_denied == 1


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_observability(
    client: httpx.AsyncClient, admin_headers: dict[str, str], db: AsyncSession, loaded_plugin: Plugin
):
    await _dispatch(db, loaded_plugin, "/ping")
    await _dispatch(db, loaded_plugin, "/未匹配命令")

    response = await client.get(f"/api/plugins/{loaded_plugin.id}/metrics", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["plugin_id"] == PLUGIN_ID
    assert data["invocations"] >= 2
    assert data["errors"] == 0, data
    assert "error_rate" in data and "avg_duration_ms" in data
    assert data["permission_denied"] == 1
    assert {"ai:request", "http:request"} <= {c["permission"] for c in data["permission_checks"]}


@pytest.mark.asyncio
async def test_metrics_endpoint_requires_view_permission(loaded_plugin: Plugin):
    # 用独立客户端避免共享 client 上登录 cookie 造成误判。
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anon:
        response = await anon.get(f"/api/plugins/{loaded_plugin.id}/metrics")
    assert response.status_code in (401, 403)
