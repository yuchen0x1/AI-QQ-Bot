"""AI 中心：多供应商配置、连通性测试、调用、备用模型降级、用量统计。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.http import set_transport


@pytest.fixture(autouse=True)
def ai_transport():
    """所有 AI / GitHub 请求都被本地 MockTransport 拦截，绝不访问外网。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            if "unreachable" in (request.url.host or ""):
                return httpx.Response(401, json={"error": {"message": "invalid api key"}})
            return httpx.Response(200, json={"data": [
                {"id": "gpt-test-chat"}, {"id": "gpt-test-mini"},
                {"id": "text-embedding-3-small"}, {"id": "tts-1"},
            ]})
        body = json.loads(request.content or b"{}")
        model = body.get("model", "")
        if model.startswith("broken"):
            return httpx.Response(503, json={"error": {"message": "upstream unavailable"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": model or "test-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "这是测试模型的回复"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        )

    set_transport(httpx.MockTransport(handler))
    yield
    set_transport(None)


async def _create_model(client: httpx.AsyncClient, headers: dict, *, name: str, model_name: str, **kwargs) -> dict:
    provider = await client.post(
        "/api/ai/providers",
        headers=headers,
        json={
            "name": name,
            "kind": "custom",
            "base_url": "https://ai.example.com/v1",
            "api_key": "sk-test-abcdefghijklmnop",
        },
    )
    assert provider.status_code in (201, 409), provider.text
    provider_id = provider.json()["id"] if provider.status_code == 201 else None
    if provider_id is None:
        providers = (await client.get("/api/ai/providers", headers=headers)).json()
        provider_id = next(p["id"] for p in providers if p["name"] == name)
    payload = {"provider_id": provider_id, "model_name": model_name, **kwargs}
    created = await client.post("/api/ai/models", headers=headers, json=payload)
    assert created.status_code in (201, 409), created.text
    models = (await client.get("/api/ai/models", headers=headers)).json()
    return next(m for m in models if m["model_name"] == model_name)


async def test_api_key_masked(client: httpx.AsyncClient, admin_headers: dict):
    await _create_model(client, admin_headers, name="测试供应商A", model_name="good-model", is_default=True)
    providers = (await client.get("/api/ai/providers", headers=admin_headers)).json()
    provider = next(p for p in providers if p["name"] == "测试供应商A")
    assert provider["has_api_key"] is True
    assert "abcdefghijklmnop" not in provider["api_key_masked"]
    assert provider["api_key_masked"].endswith("mnop")


async def test_model_connection_and_chat(client: httpx.AsyncClient, admin_headers: dict):
    model = await _create_model(
        client, admin_headers, name="测试供应商A", model_name="good-model", is_default=True, temperature=0.5
    )
    test = await client.post(f"/api/ai/models/{model['id']}/test", headers=admin_headers)
    assert test.status_code == 200
    assert test.json()["ok"] is True
    assert "连接成功" in test.json()["message"]

    chat = await client.post(
        "/api/ai/chat",
        headers=admin_headers,
        json={"model_id": model["id"], "messages": [{"role": "user", "content": "你好"}]},
    )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["ok"] is True
    assert body["content"] == "这是测试模型的回复"
    assert body["fallback_used"] is False

    summary = (await client.get("/api/ai/usage/summary", headers=admin_headers)).json()
    assert summary["calls_7d"] >= 1
    assert summary["tokens_7d"] > 0


async def test_fallback_model_used_when_primary_fails(client: httpx.AsyncClient, admin_headers: dict):
    broken = await _create_model(client, admin_headers, name="测试供应商B", model_name="broken-model", is_default=True)
    healthy = await _create_model(
        client, admin_headers, name="测试供应商C", model_name="backup-model", is_fallback=True, priority=10
    )
    resp = await client.post(
        "/api/ai/chat",
        headers=admin_headers,
        json={"model_id": broken["id"], "messages": [{"role": "user", "content": "测试降级"}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["fallback_used"] is True
    assert body["model_name"] == "backup-model"

    models = (await client.get("/api/ai/models", headers=admin_headers)).json()
    broken_after = next(m for m in models if m["id"] == broken["id"])
    assert broken_after["total_errors"] >= 1
    assert healthy["id"] in {m["id"] for m in models}


async def test_chat_without_model(client: httpx.AsyncClient, admin_headers: dict):
    resp = await client.post(
        "/api/ai/chat",
        headers=admin_headers,
        json={"model_id": 999999, "messages": [{"role": "user", "content": "hi"}]},
    )
    # 指定模型不存在时回落到默认模型
    assert resp.status_code in (200, 400)


async def test_sync_models_imports_and_dedupes(client: httpx.AsyncClient, admin_headers: dict):
    created = await client.post(
        "/api/ai/providers",
        headers=admin_headers,
        json={"name": "sync-probe", "kind": "custom", "base_url": "https://ai.example.com/v1", "api_key": "sk-sync-test-key-123"},
    )
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]
    first = (await client.post(f"/api/ai/providers/{provider_id}/sync-models", headers=admin_headers)).json()
    assert first["ok"] is True, first
    # text-embedding / tts 等非对话模型被过滤，只导入 2 个聊天模型
    assert first["fetched"] == 2 and first["created"] == 2, first
    second = (await client.post(f"/api/ai/providers/{provider_id}/sync-models", headers=admin_headers)).json()
    assert second["created"] == 0 and second["existing"] == 2, second
    models = (await client.get("/api/ai/models", headers=admin_headers)).json()
    mine = {m["model_name"]: m for m in models if m["provider_id"] == provider_id}
    assert set(mine) == {"gpt-test-chat", "gpt-test-mini"}
    assert all(m["enabled"] and m["priority"] == 100 and not m["is_default"] for m in mine.values())


async def test_sync_models_reports_unreachable_provider(client: httpx.AsyncClient, admin_headers: dict):
    created = await client.post(
        "/api/ai/providers",
        headers=admin_headers,
        json={"name": "sync-unreachable", "kind": "custom", "base_url": "https://unreachable.example.com/v1", "api_key": "sk-x"},
    )
    assert created.status_code == 201, created.text
    result = (await client.post(f"/api/ai/providers/{created.json()['id']}/sync-models", headers=admin_headers)).json()
    assert result["ok"] is False and result["created"] == 0
    assert "获取模型列表失败" in result["message"]
