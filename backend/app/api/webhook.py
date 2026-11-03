"""GitHub Webhook 接收端点：HMAC-SHA256 验签 + 事件去重。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.db.session import get_db
from app.models import GithubRepository
from app.services.github.monitor import handle_webhook_payload
from app.services.logs import write_log

logger = logging.getLogger("qbot.webhook")
router = APIRouter(prefix="/webhook", tags=["Webhook"])


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret:
        return False
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github/{repo_id}")
async def github_webhook(repo_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    repo = await db.get(GithubRepository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    body = await request.body()
    secret = decrypt_secret(repo.webhook_secret_enc) or ""
    signature = request.headers.get("x-hub-signature-256")
    if not secret:
        raise HTTPException(status_code=409, detail="必须为 Webhook 配置 Secret")
    if not verify_signature(secret, body, signature):
        await write_log(
            db,
            level="WARNING",
            category="github",
            message=f"Webhook 验签失败：{repo.full_name}（来源 {request.client.host if request.client else 'unknown'}）",
            context={"repo": repo.full_name},
        )
        raise HTTPException(status_code=401, detail="Webhook 签名校验失败")
    event_type = request.headers.get("x-github-event", "unknown")
    delivery = request.headers.get("x-github-delivery")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON") from exc

    if event_type == "ping":
        return {"ok": True, "message": "webhook ping 成功", "zen": payload.get("zen")}
    if payload.get("repository"):
        full_name = str(payload["repository"].get("full_name") or "").lower()
        if full_name and full_name != repo.full_name.lower():
            raise HTTPException(status_code=400, detail="Webhook 负载的仓库与目标仓库不一致")

    result = await handle_webhook_payload(db, repo, payload, delivery_id=delivery, event_type=event_type)
    return result
