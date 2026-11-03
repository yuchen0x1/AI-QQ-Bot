"""统一 HTTP 客户端工厂（便于测试注入 MockTransport）。"""

from __future__ import annotations

import httpx

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def new_client(*, timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=_transport, follow_redirects=True)
