"""Authenticated web API's narrow bridge to the host's independent update service."""

import httpx

from app.core.config import settings


class InstallerUnavailable(Exception):
    pass


async def installer_rpc(method: str = "GET", payload: dict | None = None) -> dict:
    if not settings.update_socket:
        raise InstallerUnavailable("当前部署尚未安装自动升级服务，请按部署文档安装一次升级入口")
    try:
        transport = httpx.AsyncHTTPTransport(uds=settings.update_socket)
        async with httpx.AsyncClient(transport=transport, timeout=8) as client:
            response = await client.request(method, "http://updater/install", json=payload)
        data = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise InstallerUnavailable("升级服务暂时无法连接，请稍后重试") from exc
    if response.status_code >= 400:
        raise InstallerUnavailable(data.get("detail", "升级请求未被接受"))
    return data


async def installer_state() -> dict:
    try:
        return {"available": True, **await installer_rpc()}
    except InstallerUnavailable as exc:
        return {"available": False, "reason": str(exc), "job": None}
