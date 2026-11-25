"""Outbound URL validation for administrator-supplied API endpoints.

These URLs are combined with encrypted credentials before every request.  A
malicious or mistaken private endpoint would otherwise turn a normal "test
connection" into a credentialed SSRF probe against localhost or cloud metadata.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

_LOCAL_MODEL_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))


class OutboundURLError(ValueError):
    pass


def _blocked_reason(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return _blocked_reason(address.ipv4_mapped)
    if not address.is_global or address.is_multicast:
        return "不允许访问私有、回环、链路本地或保留 IP 地址"
    return None


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    return parsed.scheme.lower(), (parsed.hostname or "").rstrip(".").lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def _is_allowed_local_base(base_url: str, allowlist: Sequence[str]) -> bool:
    """An exception names a complete endpoint, never a subnet or wildcard."""
    try:
        requested = urlsplit(base_url)
        for item in allowlist:
            allowed = urlsplit(item.strip().rstrip("/"))
            if (
                allowed.scheme in {"http", "https"}
                and allowed.hostname
                and not (allowed.username or allowed.password or allowed.query or allowed.fragment)
                and _origin(base_url) == _origin(item)
                and requested.path.rstrip("/") == allowed.path.rstrip("/")
            ):
                return True
    except ValueError:
        return False
    return False


@dataclass(frozen=True)
class OutboundTarget:
    url: str
    host: str
    addresses: tuple[str, ...]


def resolve_outbound_target(
    value: str,
    *,
    allow_private: bool = False,
    allow_http: bool = False,
    private_allowlist: Sequence[str] = (),
    base_url: str | None = None,
) -> OutboundTarget:
    """Validate every A/AAAA answer and return the exact IPs to connect to.

    Callers must pin these addresses in their transport. Merely resolving here
    and allowing a second DNS lookup at connect time permits DNS rebinding.
    """
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise OutboundURLError("接口地址不能为空")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise OutboundURLError("接口地址格式或端口无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OutboundURLError("接口地址必须是包含主机名的 HTTP(S) 地址")
    if parsed.username or parsed.password or parsed.fragment:
        raise OutboundURLError("接口地址不能携带用户凭据或 fragment")
    if parsed.scheme == "http" and not allow_http:
        raise OutboundURLError("接口地址必须使用 HTTPS（明确允许的 Ollama 地址除外）")
    if base_url and _origin(raw) != _origin(base_url):
        raise OutboundURLError("请求地址与配置的供应商来源不一致")
    host = parsed.hostname.rstrip(".").lower()
    local_exception = allow_private or _is_allowed_local_base(base_url or raw, private_allowlist)
    try:
        address = ipaddress.ip_address(host)
        addresses = (str(address),)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, port or (80 if parsed.scheme == "http" else 443), type=socket.SOCK_STREAM)
            addresses = tuple(dict.fromkeys(item[4][0] for item in resolved))
        except OSError as exc:
            raise OutboundURLError("接口地址无法解析") from exc
    if not addresses:
        raise OutboundURLError("接口地址无法解析")
    for item in addresses:
        try:
            address = ipaddress.ip_address(item)
        except ValueError as exc:
            raise OutboundURLError("DNS 返回无效 IP 地址") from exc
        # Metadata/link-local targets stay forbidden even for a configured
        # local-model exception. Loopback/RFC1918/ULA require the exact allowlist.
        effective_address = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address
        if effective_address.is_link_local or effective_address.is_multicast or effective_address.is_unspecified:
            raise OutboundURLError("不允许访问链路本地、元数据、组播或未指定 IP 地址")
        if isinstance(address, ipaddress.IPv6Address) and (
            address in ipaddress.ip_network("64:ff9b::/96")
            or address in ipaddress.ip_network("64:ff9b:1::/48")
            or address.sixtofour is not None
            or address.teredo is not None
        ):
            raise OutboundURLError("不允许使用 IPv6 地址转换或隧道目标")
        reason = _blocked_reason(address)
        permitted_local = local_exception and (
            effective_address.is_loopback
            or any(effective_address.version == network.version and effective_address in network
                   for network in _LOCAL_MODEL_NETWORKS)
        )
        if reason and not permitted_local:
            raise OutboundURLError(reason)
    return OutboundTarget(raw, host, addresses)


def validate_outbound_base_url(
    value: str,
    *,
    allow_private: bool = False,
    allow_http: bool = False,
    private_allowlist: Sequence[str] = (),
) -> str:
    """Validate and normalise a base URL; returns the normalised URL."""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise OutboundURLError("接口地址不能为空")
    if len(raw) > 255:
        raise OutboundURLError("接口地址过长")
    try:
        query = urlsplit(raw).query
    except ValueError as exc:
        raise OutboundURLError("接口地址格式无效") from exc
    if query:
        raise OutboundURLError("接口基础地址不能携带查询参数")
    return resolve_outbound_target(
        raw, allow_private=allow_private, allow_http=allow_http, private_allowlist=private_allowlist
    ).url

