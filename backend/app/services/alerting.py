"""系统告警通知服务：支持 飞书 / 钉钉 / 企业微信 / 通用 Webhook 告警推送。

具备自动通道识别、限频防刷、敏感信息脱敏与异步分发。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select

from app.core.http import new_client
from app.core.logging import mask_text
from app.db.session import SessionLocal
from app.models import SystemSetting

logger = logging.getLogger("qbot.alerting")

# 相同告警内容防刷频间隔（秒）
DEBOUNCE_SECONDS = 180.0
_last_sent: dict[str, float] = {}


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
        async with SessionLocal() as db:
            url_row = await db.scalar(select(SystemSetting).where(SystemSetting.key == "alert_webhook_url"))
            webhook_url = str((url_row.value or {}).get("value") or "").strip() if url_row else ""
            if not webhook_url:
                return False

            type_row = await db.scalar(select(SystemSetting).where(SystemSetting.key == "alert_channel_type"))
            channel_type = str((type_row.value or {}).get("value") or "auto") if type_row else "auto"

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
