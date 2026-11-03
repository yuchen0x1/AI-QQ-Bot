"""NapCat WebUI 扫码登录桥接。

NapCat 只负责 QQ 登录和 OneBot 协议端；本服务只调用固定的登录接口，
不把 NapCat WebUI 令牌或临时 Credential 暴露给浏览器。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("qbot.napcat")


class NapCatError(RuntimeError):
    """NapCat 管理接口错误。"""


@dataclass(frozen=True)
class NapCatInstance:
    id: str
    name: str
    webui_url: str
    webui_token: str
    api_base: str
    ws_url: str
    access_token: str


@dataclass
class _Credential:
    value: str
    expires_at: float


def _clean_base(value: str) -> str:
    return value.strip().rstrip("/")


def _unwrap(body: dict[str, Any], *, operation: str) -> Any:
    """解析 NapCat WebUI 的 {code, message, data} 响应。"""
    if body.get("code") not in (0, None):
        raise NapCatError(f"NapCat {operation} 失败：{body.get('message') or body.get('code')}")
    return body.get("data")


class NapCatBridge:
    def __init__(self) -> None:
        self._credentials: dict[str, _Credential] = {}

    def instances(self) -> list[NapCatInstance]:
        return [NapCatInstance(**item) for item in settings.napcat_instances()]

    def get_instance(self, instance_id: str | None = None) -> NapCatInstance:
        instances = self.instances()
        if not instances:
            raise NapCatError("未配置 NapCat 扫码服务，请先配置 NAPCAT_WEBUI_URL 和 NAPCAT_WEBUI_TOKEN")
        if instance_id:
            for instance in instances:
                if instance.id == instance_id:
                    return instance
            raise NapCatError(f"NapCat 实例不存在：{instance_id}")
        return instances[0]

    def public_instances(self) -> list[dict[str, str]]:
        return [{"id": item.id, "name": item.name} for item in self.instances()]

    async def _credential(self, instance: NapCatInstance, client: httpx.AsyncClient) -> str:
        cached = self._credentials.get(instance.id)
        if cached and cached.expires_at > time.time() + 30:
            return cached.value
        token_hash = hashlib.sha256(f"{instance.webui_token}.napcat".encode("utf-8")).hexdigest()
        response = await client.post("/api/auth/login", json={"hash": token_hash})
        if response.status_code >= 400:
            raise NapCatError(f"NapCat WebUI 登录失败：HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise NapCatError("NapCat WebUI 登录返回非 JSON 数据") from exc
        data = _unwrap(body, operation="WebUI 登录") or {}
        credential = data.get("Credential") if isinstance(data, dict) else None
        if not credential:
            raise NapCatError("NapCat WebUI 登录未返回 Credential")
        self._credentials[instance.id] = _Credential(value=str(credential), expires_at=time.time() + 3300)
        return str(credential)

    async def _request(
        self,
        instance: NapCatInstance,
        path: str,
        *,
        method: str = "POST",
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not instance.webui_token:
            raise NapCatError(f"NapCat 实例 {instance.name} 未配置 WebUI 令牌")
        timeout = httpx.Timeout(12.0, connect=5.0)
        async with httpx.AsyncClient(base_url=_clean_base(instance.webui_url), timeout=timeout) as client:
            credential = await self._credential(instance, client)
            headers = {"Authorization": f"Bearer {credential}", "Cache-Control": "no-store"}
            response = await client.request(method, path, json=json_body, headers=headers)
            if response.status_code == 401:
                self._credentials.pop(instance.id, None)
                credential = await self._credential(instance, client)
                headers["Authorization"] = f"Bearer {credential}"
                response = await client.request(method, path, json=json_body, headers=headers)
            if response.status_code >= 400:
                raise NapCatError(f"NapCat {path} 返回 HTTP {response.status_code}")
            try:
                body = response.json()
            except ValueError as exc:
                raise NapCatError(f"NapCat {path} 返回非 JSON 数据") from exc
            return _unwrap(body, operation=path)

    async def get_qr(self, instance: NapCatInstance) -> str:
        data = await self._request(instance, "/api/QQLogin/GetQQLoginQrcode") or {}
        if isinstance(data, dict):
            qrcode = data.get("qrcode") or data.get("qrcodeurl") or data.get("url")
        else:
            qrcode = data
        if not qrcode:
            raise NapCatError("NapCat 暂未返回二维码，请稍后重试")
        return str(qrcode)

    async def status(self, instance: NapCatInstance) -> dict[str, Any]:
        data = await self._request(instance, "/api/QQLogin/CheckLoginStatus") or {}
        return dict(data) if isinstance(data, dict) else {}

    async def refresh_qr(self, instance: NapCatInstance) -> str:
        data = await self._request(instance, "/api/QQLogin/RefreshQRcode") or {}
        if data.get("restarting"):
            raise NapCatError("NapCat 正在重连，请稍后刷新")
        if isinstance(data, dict):
            qrcode = data.get("qrcodeurl") or data.get("qrcode") or data.get("url")
        else:
            qrcode = data
        if not qrcode:
            raise NapCatError("NapCat 暂未返回新的二维码")
        return str(qrcode)

    async def get_login_info(self, instance: NapCatInstance) -> dict[str, Any]:
        data = await self._request(instance, "/api/QQLogin/GetQQLoginInfo") or {}
        return dict(data) if isinstance(data, dict) else {}

    async def configure_onebot(self, instance: NapCatInstance) -> None:
        """登录成功后，确保 NapCat 的 HTTP/WS 服务与账号槽位一致。"""
        if not instance.api_base or not instance.ws_url or not instance.access_token:
            raise NapCatError("扫码实例缺少 OneBot API/WS 地址或访问令牌，请补齐服务器配置")
        config = await self._request(instance, "/api/OB11Config/GetConfig")
        if not isinstance(config, dict):
            raise NapCatError("NapCat OneBot 配置格式无效")
        network = config.setdefault("network", {})
        http_servers = network.setdefault("httpServers", [])
        ws_servers = network.setdefault("websocketServers", [])
        self._upsert_http(http_servers, instance)
        self._upsert_ws(ws_servers, instance)
        # remove stale entries left by previous failed setup attempts. NapCat
        # cannot bind the same port twice and otherwise reports EADDRINUSE.
        network["httpServers"] = [item for item in http_servers if item.get("name") == "qbot-http"]
        network["websocketServers"] = [item for item in ws_servers if item.get("name") == "qbot-ws"]
        payload = {"config": json.dumps(config, ensure_ascii=False)}
        await self._request(instance, "/api/OB11Config/SetConfig", json_body=payload)

    @staticmethod
    def _find_or_add(
        items: list[dict[str, Any]],
        *,
        name: str,
        port: int,
        prefer_existing_port: bool = True,
    ) -> dict[str, Any]:
        """复用同端口已有服务，避免 SetConfig 后重复监听同一端口。

        NapCat 初始配置通常会预置一个名为 ``ws`` 的 WebSocket 服务。
        如果直接再追加 ``qbot-ws``，NapCat 会尝试启动两个 3001 监听器，
        结果就是登录成功但 OneBot 账号显示 error。因此先按名称查找，
        再按端口复用，最后才创建新条目。
        """
        item = next((x for x in items if x.get("name") == name), None)
        if item is None and prefer_existing_port:
            item = next((x for x in items if int(x.get("port") or 0) == port), None)
        if item is None:
            item = {"name": name}
            items.append(item)
        item["name"] = name
        return item

    @classmethod
    def _upsert_http(cls, items: list[dict[str, Any]], instance: NapCatInstance) -> None:
        item = cls._find_or_add(items, name="qbot-http", port=3000)
        item.update(
            {
                "enable": True,
                "port": 3000,
                "host": "0.0.0.0",
                "enableCors": False,
                "enableWebsocket": False,
                "messagePostFormat": "array",
                "token": instance.access_token,
                "debug": False,
            }
        )

    @classmethod
    def _upsert_ws(cls, items: list[dict[str, Any]], instance: NapCatInstance) -> None:
        item = cls._find_or_add(items, name="qbot-ws", port=3001)
        item.update(
            {
                "enable": True,
                "host": "0.0.0.0",
                "port": 3001,
                "messagePostFormat": "array",
                "reportSelfMessage": False,
                "token": instance.access_token,
                "enableForcePushEvent": True,
                "debug": False,
                "heartInterval": 30000,
            }
        )


napcat_bridge = NapCatBridge()
