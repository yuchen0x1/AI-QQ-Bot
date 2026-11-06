"""QQ 官方机器人 Webhook 回调端点。

平台回调方式设为 Webhook 时：
- 首次配置回调地址会推送 op=13 验证请求（无签名头），需用 AppSecret 派生的
  Ed25519 私钥签 ``event_ts + plain_token`` 并返回。
- 之后的事件推送为 op=0，带 ``X-Signature-Ed25519`` / ``X-Signature-Timestamp``，
  验签通过后注入运行中的适配器事件队列，复用与 WebSocket 完全相同的业务链路。

本端点不需要登录态，安全性完全由 Ed25519 签名保证；请勿在反代上剥离签名头。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.qq_official import QQOfficialAdapter
from app.core.config import settings
from app.core.security import decrypt_secret
from app.db.session import get_db
from app.models import Account
from app.services.account_manager import account_manager
from app.services.logs import write_log
from app.services.qq_webhook_crypto import sign_callback_validation, verify_event_signature

logger = logging.getLogger("qbot.qqbot.webhook")

router = APIRouter(prefix="/qqbot/webhook", tags=["QQ官方机器人Webhook"])
# 兼容把回调地址直接填成 https://域名/webhook 的旧部署（由 Nginx 转发到此路由）。
legacy_router = APIRouter(tags=["QQ官方机器人Webhook"])

OP_DISPATCH = 0
OP_CALLBACK_VALIDATION = 13
MAX_BODY_BYTES = 2 * 1024 * 1024
OFFLINE_LOG_INTERVAL_SECONDS = 30.0

# 账号未在线时平台可能持续重推，这里做内存级日志节流，避免把系统日志刷爆。
_offline_logged_at: dict[int, float] = {}


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "detail": detail})


def _should_log_offline(account_db_id: int) -> bool:
    now = time.monotonic()
    last = _offline_logged_at.get(account_db_id, 0.0)
    if now - last < OFFLINE_LOG_INTERVAL_SECONDS:
        return False
    _offline_logged_at[account_db_id] = now
    return True


async def _trace_context(request: Request, **extra: Any) -> dict[str, Any]:
    context = dict(extra)
    trace_id = request.headers.get("X-Tps-Trace-Id") or request.headers.get("X-Tps-trace-ID")
    if trace_id:
        context["trace_id"] = trace_id
    return context


async def _resolve_account(
    db: AsyncSession, path_app_id: str, header_app_id: str
) -> tuple[Account | None, str]:
    """按回调地址 / 请求头里的 AppID 找到账号。

    平台配置回调地址时很容易把示例占位符（例如 ``1029xxxx``）一起粘进去，
    这种地址平台仍会正常推送事件。为了不让一个字符配错就整条链路失效，
    这里按「路径 → 请求头 → 唯一官方账号」的顺序回退，安全仍由 Ed25519 验签保证。
    """
    for candidate in (path_app_id, header_app_id):
        if not candidate:
            continue
        found = await db.scalar(
            select(Account).where(Account.app_id == candidate, Account.protocol == "qq_official")
        )
        if found:
            return found, ""
    rows = list(
        await db.scalars(
            select(Account).where(Account.protocol == "qq_official", Account.enabled.is_(True))
        )
    )
    if len(rows) == 1:
        return rows[0], (
            f"回调地址中的 AppID（{path_app_id or header_app_id or '-'}）与账号实际 AppID"
            f"（{rows[0].app_id}）不一致，已自动回退到唯一官方账号；建议把平台回调地址改成"
            f"https://<你的域名>/api/qqbot/webhook/{rows[0].app_id}"
        )
    return None, ""


async def handle_callback(request: Request, app_id: str | None, db: AsyncSession) -> JSONResponse:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _error(413, "回调请求体过大")
    path_app_id = (app_id or "").strip()
    header_app_id = (request.headers.get("X-Bot-Appid") or "").strip()
    resolved_app_id = path_app_id or header_app_id
    if not resolved_app_id:
        return _error(
            400,
            "缺少 BotAppID：请使用 /qqbot/webhook/{app_id} 形式的回调地址，或提供 X-Bot-Appid 请求头",
        )
    try:
        payload = json.loads(body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return _error(400, "回调请求体不是合法 JSON")
    if not isinstance(payload, dict):
        return _error(400, "回调请求体必须是 JSON 对象")

    account, fallback_note = await _resolve_account(db, path_app_id, header_app_id)
    if not account:
        return _error(404, "未找到该 AppID 对应的 QQ 官方机器人账号，请先在后台创建账号")
    if fallback_note and _should_log_offline(account.id):
        await write_log(
            db,
            level="WARNING",
            category="qq",
            message=f"QQ Webhook 回调地址异常：{fallback_note}",
            account_id=account.id,
            context=await _trace_context(request, app_id=resolved_app_id),
        )
    secret = decrypt_secret(account.app_secret_enc) or ""
    if not secret:
        return _error(409, "该账号的 AppSecret 缺失或无法解密，请在后台重新填写")

    op = payload.get("op")
    if op == OP_CALLBACK_VALIDATION:
        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        plain_token = str(data.get("plain_token") or "")
        event_ts = str(data.get("event_ts") or "")
        if not plain_token or not event_ts:
            return _error(400, "回调验证请求缺少 plain_token / event_ts")
        signature = sign_callback_validation(secret, event_ts, plain_token)
        await write_log(
            db,
            level="INFO",
            category="qq",
            message=f"QQ 官方机器人 {account.name} 通过 Webhook 回调地址验证",
            account_id=account.id,
            context=await _trace_context(request, app_id=resolved_app_id),
        )
        return JSONResponse({"plain_token": plain_token, "signature": signature})

    if op != OP_DISPATCH:
        # 平台可能推送心跳 / 其它 OpCode，Webhook 模式下无需维护长连接状态。
        return JSONResponse({"ok": True, "ignored_op": op})

    ok, reason = verify_event_signature(
        secret,
        request.headers.get("X-Signature-Timestamp") or "",
        body,
        request.headers.get("X-Signature-Ed25519") or "",
        max_age_seconds=settings.qqbot_webhook_max_age_seconds,
    )
    if not ok:
        logger.warning("QQ Webhook 验签失败 app=%s: %s", resolved_app_id, reason)
        await write_log(
            db,
            level="WARNING",
            category="qq",
            message=f"QQ Webhook 验签失败：{reason}",
            account_id=account.id,
            context=await _trace_context(request, app_id=resolved_app_id),
        )
        return _error(401, f"Webhook 验签失败：{reason}")

    adapter = account_manager.adapter(account.id)
    if not isinstance(adapter, QQOfficialAdapter):
        if _should_log_offline(account.id):
            await write_log(
                db,
                level="WARNING",
                category="qq",
                message="QQ Webhook 事件被拒绝：账号尚未启动，请在后台启动该机器人账号",
                account_id=account.id,
                context=await _trace_context(request, app_id=resolved_app_id, event_type=payload.get("t")),
            )
        # 5xx 让平台可以重试，而不是静默丢弃用户消息。
        return _error(503, "该机器人账号尚未启动：请在后台启动账号")

    # WebSocket 模式下同样接受 Webhook 推送：平台切换回调方式后无需重启本服务，
    # 重复事件由适配器内部的去重键（事件 ID + msg_idx）过滤。
    await adapter.feed_event(payload)
    return JSONResponse({"ok": True})


def _probe_response(app_id: str | None) -> JSONResponse:
    """平台保存回调地址前后会做可达性探测（GET），必须返回 200 而不是 405。"""
    return JSONResponse(
        {
            "ok": True,
            "endpoint": "qqbot-webhook",
            "app_id": app_id or "",
            "note": "该地址用于接收 QQ 开放平台事件推送，请使用 POST 回调",
        }
    )


@router.post("/{app_id}")
async def webhook_with_appid(app_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await handle_callback(request, app_id, db)


@router.post("")
async def webhook_by_header(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await handle_callback(request, None, db)


@legacy_router.post("/webhook")
async def webhook_legacy(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await handle_callback(request, None, db)


@router.get("/{app_id}")
async def webhook_probe(app_id: str) -> JSONResponse:
    return _probe_response(app_id)


@router.head("/{app_id}")
async def webhook_probe_head(app_id: str) -> JSONResponse:
    return _probe_response(app_id)


@router.get("")
async def webhook_probe_root() -> JSONResponse:
    return _probe_response(None)


@legacy_router.get("/webhook")
async def webhook_probe_legacy() -> JSONResponse:
    return _probe_response(None)
