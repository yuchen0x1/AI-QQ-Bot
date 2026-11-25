"""Permission and cookie contracts on the installed FastAPI/Starlette stack."""

from __future__ import annotations

import uuid
import asyncio
import contextlib
import json
from urllib.parse import urlencode

import httpx
import pytest

from app.core.config import settings
from app.main import app


async def _viewer_headers(client, admin_headers):
    roles = (await client.get("/api/roles", headers=admin_headers)).json()
    role = next(row for row in roles if row["name"] == "viewer")
    username = f"console-viewer-{uuid.uuid4().hex[:8]}"
    created = await client.post("/api/users", headers=admin_headers, json={
        "username": username, "password": "Boundary@12345", "role_id": role["id"],
    })
    assert created.status_code == 201
    login = await client.post("/api/auth/login", json={"username": username, "password": "Boundary@12345"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_viewer_cannot_trigger_console_writes_or_task_preview(client, admin_headers, mock_account):
    headers = await _viewer_headers(client, admin_headers)
    account_id = mock_account["id"]
    cases = [
        (f"/api/accounts/{account_id}/start", None),
        (f"/api/accounts/{account_id}/stop", None),
        (f"/api/accounts/{account_id}/test-connection", None),
        ("/api/messages/send", {"account_id": account_id, "qq_group": 900001, "content": "forbidden"}),
        ("/api/groups/sync/99999", None),
        ("/api/groups/99999/action", {"action": "ban_all"}),
        ("/api/tasks/99999/run", None),
        ("/api/tasks/preview", {"name": "forbidden preview", "task_type": "health_check",
                                "schedule_kind": "interval", "interval_seconds": 600}),
    ]
    for path, payload in cases:
        response = await client.post(path, headers=headers, json=payload)
        assert response.status_code == 403, f"{path}: {response.status_code} {response.text}"


@pytest.mark.parametrize("production", [False, True])
async def test_login_cookie_auth_and_logout_on_updated_framework(client, monkeypatch, production):
    monkeypatch.setattr(settings, "env", "production" if production else "development")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cookie.example.test") as browser:
        login = await browser.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
        assert ("; secure" in cookie) is production
        assert (await browser.get("/api/auth/me")).status_code == 200
        logout = await browser.post("/api/auth/logout")
        assert logout.status_code == 200
        assert (await browser.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize("path", ["/api/ws/events", "/api/ws/logs", "/api/ws/status"])
async def test_real_asgi_websocket_ticket_handshake_on_updated_framework(client, admin_headers, path):
    ticket = (await client.post("/api/ws/ticket", headers=admin_headers)).json()["ticket"]
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    await incoming.put({"type": "websocket.connect"})
    scope = {
        "type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1", "scheme": "ws", "server": ("test", 80), "client": ("127.0.0.1", 10000),
        "root_path": "", "path": path, "raw_path": path.encode(), "headers": [],
        "query_string": urlencode({"ticket": ticket}).encode(), "subprotocols": [], "state": {},
    }

    async def send(message):
        await outgoing.put(message)

    task = asyncio.create_task(app(scope, incoming.get, send))
    try:
        accepted = await asyncio.wait_for(outgoing.get(), timeout=3)
        assert accepted["type"] == "websocket.accept", accepted
        message = await asyncio.wait_for(outgoing.get(), timeout=3)
        assert message["type"] == "websocket.send", message
        assert json.loads(message["text"])["type"] in {"connected", "status"}
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
