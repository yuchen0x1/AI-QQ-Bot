"""统一 HTTP 客户端工厂（便于测试注入 MockTransport）。"""

from __future__ import annotations

import httpx

from app.core.ssrf import OutboundTarget, OutboundURLError

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


class PinnedAddressTransport(httpx.AsyncBaseTransport):
    """Connect to a validated IP while preserving Host and TLS verification."""

    def __init__(self, target: OutboundTarget, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.target = target
        self.inner = inner or httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.rstrip(".").lower() != self.target.host:
            raise OutboundURLError("请求目标与已验证的主机不一致")
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=self.target.addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": self.target.host},
        )
        return await self.inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self.inner.aclose()


def new_client(
    *, timeout: float = 30.0, follow_redirects: bool = False, target: OutboundTarget | None = None
) -> httpx.AsyncClient:
    """Build the shared HTTP client.

    Redirect handling is opt-in per caller rather than being hidden in the
    transport.  In particular, callers sending credentials or administrator
    supplied payloads must disable redirects so that a validated public URL
    cannot silently turn into a request to a private host.
    """
    # Injected transports never open sockets. DNS/IP validation still runs in
    # the caller, so tests exercise the same policy without bypass flags.
    transport = _transport or (PinnedAddressTransport(target) if target else None)
    return httpx.AsyncClient(
        timeout=timeout, transport=transport, follow_redirects=follow_redirects, trust_env=target is None
    )
