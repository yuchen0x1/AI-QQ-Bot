"""Outbound URL validation for administrator-supplied API endpoints.

These URLs are combined with encrypted credentials before every request.  A
malicious or mistaken private endpoint would otherwise turn a normal "test
connection" into a credentialed SSRF probe against localhost or cloud metadata.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit


class OutboundURLError(ValueError):
    pass


_SKIP_DNS_RESOLUTION = os.getenv("QBOT_TEST_DISABLE_DNS_SSRF", "").lower() in {"1", "true", "yes"}


def _blocked_reason(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return "不允许访问私有、回环、链路本地或保留 IP 地址"
    return None


def validate_outbound_base_url(
    value: str,
    *,
    allow_private: bool = False,
    allow_http: bool = False,
) -> str:
    """Validate and normalise a base URL; returns the normalised URL."""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise OutboundURLError("接口地址不能为空")
    if len(raw) > 255:
        raise OutboundURLError("接口地址过长")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise OutboundURLError("接口地址格式无效") from exc
    if parsed.scheme not in {"http", "https"}:
        raise OutboundURLError("接口地址仅支持 http 或 https")
    if not parsed.hostname:
        raise OutboundURLError("接口地址必须包含主机名")
    if parsed.username or parsed.password or parsed.fragment:
        raise OutboundURLError("接口地址不能携带用户凭据或 fragment")
    if parsed.scheme == "http" and not allow_http:
        raise OutboundURLError("接口地址必须使用 HTTPS（Ollama 本地地址除外）")
    try:
        port = parsed.port
    except ValueError as exc:
        raise OutboundURLError("接口地址端口无效") from exc

    host = parsed.hostname.rstrip(".").lower()
    if not allow_private and not _SKIP_DNS_RESOLUTION:
        addresses: set[str] = {host}
        try:
            ipaddress.ip_address(host)
        except ValueError:
            try:
                resolved = socket.getaddrinfo(
                    host,
                    port or (80 if parsed.scheme == "http" else 443),
                    type=socket.SOCK_STREAM,
                )
            except OSError as exc:
                raise OutboundURLError(f"接口地址无法解析：{exc}") from exc
            if not resolved:
                raise OutboundURLError("接口地址无法解析")
            addresses = {item[4][0] for item in resolved}

        for item in addresses:
            try:
                reason = _blocked_reason(ipaddress.ip_address(item))
            except ValueError:
                continue
            if reason:
                raise OutboundURLError(reason)
    return raw

