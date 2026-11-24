"""统一 HTTP 客户端工厂（便于测试注入 MockTransport）。"""

from __future__ import annotations

import httpx

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def new_client(*, timeout: float = 30.0, follow_redirects: bool = True) -> httpx.AsyncClient:
    """Build the shared HTTP client.

    Redirect handling is opt-in per caller rather than being hidden in the
    transport.  In particular, callers sending credentials or administrator
    supplied payloads must disable redirects so that a validated public URL
    cannot silently turn into a request to a private host.
    """
    return httpx.AsyncClient(timeout=timeout, transport=_transport, follow_redirects=follow_redirects)
