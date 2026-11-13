"""系统告警通知服务：支持 飞书 / 钉钉 / 企业微信 / 通用 Webhook 告警推送。

具备自动通道识别、限频防刷、敏感信息脱敏与异步分发。
"""

from __future__ import annotations

import logging
import ipaddress
from urllib.parse import urlsplit
import time
from typing import Any


from app.core.http import new_client
from app.core.config import settings
from app.core.logging import mask_text
from app.db.session import SessionLocal

logger = logging.getLogger("qbot.alerting")

# 相同告警内容防刷频间隔（秒）
DEBOUNCE_SECONDS = 180.0
_last_sent: dict[str, float] = {}


def validate_webhook_url(url: str, *, allow_private: bool | None = None) -> tuple[bool, str]:
    """校验告警回调地址，阻断常见 SSRF 目标。

    告警地址由管理员在控制台配置，但后台进程仍不应被借此访问本机、云元数据
    或容器管理网段。这里不限制第三方域名，只拒绝非 HTTP(S)、带用户凭据、
    localhost / 单标签主机名，以及私有/回环/链路本地等 IP 字面量。
    """
    raw = str(url or "").strip()
    if not raw or len(raw) > 2048:
        return False, "Webhook 地址为空或过长"
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port  # 触发非法端口的 ValueError
    except ValueError:
        return False, "Webhook 地址格式无效"
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "Webhook 仅支持 http 或 https"
    if not host or parsed.username or parsed.password:
        return False, "Webhook 地址必须包含主机名且不能携带用户凭据"
    if parsed.fragment:
        return False, "Webhook 地址不能包含 fragment"
    host_lower = host.rstrip(".").lower()
    if host_lower in {"localhost", "localhost.localdomain", "ip6-localhost"} or "." not in host_lower:
        return False, "Webhook 不允许访问本机或单标签内网主机"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    private_allowed = settings.alert_allow_private_networks if allow_private is None else allow_private
    if address and not private_allowed and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return False, "Webhook 不允许访问私有、回环或保留 IP 地址"
    _ = port
    return True, ""


def _detect_channel(url: str, override: str | None = None) -> str:
    if override and override != "auto":
        return override
    url_lower = url.lower()
    if "feishu.cn" in url_lower or "larksuite.com" in url_lower:
        return "feishu"
    if "dingtalk.com" in url_lower:
        return "dingtalk"
    if "weixin.qq.com" in url_lower or "qyapi.weixin.qq.com" in url_lower:
        return "wechat"
    return "custom"


def _build_payload(channel: str, title: str, content: str) -> dict[str, Any]:
    safe_title = mask_text(title)
    safe_content = mask_text(content)
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    full_text = f"【QBot 平台告警】{safe_title}\n时间：{now_str}\n\n{safe_content}"

    if channel == "feishu":
        return {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"🚨 QBot 异常告警：{safe_title}",
                        "content": [
                            [{"tag": "text", "text": f"时间：{now_str}\n"}],
                            [{"tag": "text", "text": safe_content}],
                        ],
                    }
                }
            },
        }
    elif channel == "dingtalk":
        return {
            "msgtype": "markdown",
            "markdown": {
                "title": f"QBot 告警：{safe_title}",
                "text": f"### 🚨 QBot 异常告警：{safe_title}\n\n**时间**：{now_str}\n\n> {safe_content}",
            },
        }
    elif channel == "wechat":
        return {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### <font color=\"warning\">QBot 异常告警</font>\n**标题**：{safe_title}\n**时间**：{now_str}\n> {safe_content}",
            },
        }
    else:  # custom / fallback
        return {
            "title": safe_title,
            "text": full_text,
            "level": "ERROR",
            "timestamp": int(time.time()),
        }


async def send_alert(title: str, content: str, *, force: bool = False) -> bool:
    """异步发送系统告警通知。"""
    key = f"{title}:{content[:100]}"
    now = time.monotonic()
    if not force:
        last = _last_sent.get(key, 0.0)
        if now - last < DEBOUNCE_SECONDS:
            logger.debug("告警已在节流窗口内抑制：%s", title)
            return False
        _last_sent[key] = now
        # 简单清理过期 key
        if len(_last_sent) > 500:
            for k, ts in list(_last_sent.items()):
                if now - ts > DEBOUNCE_SECONDS * 2:
                    _last_sent.pop(k, None)

    try:
        from app.services.settings_store import read_setting

        async with SessionLocal() as db:
            webhook_url = str(await read_setting(db, "alert_webhook_url", "") or "").strip()
            if not webhook_url:
                return False
            channel_type = str(await read_setting(db, "alert_channel_type", "auto") or "auto")

        valid, reason = validate_webhook_url(webhook_url)
        if not valid:
            logger.warning("告警 Webhook 地址被拒绝：%s", reason)
            return False

        channel = _detect_channel(webhook_url, channel_type)
        payload = _build_payload(channel, title, content)

        async with new_client(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning("推送告警失败 HTTP %s: %s", resp.status_code, resp.text[:200])
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("发送系统告警异常：%s", exc)
        return False
