"""API 依赖：JWT 认证、RBAC 校验、客户端 IP。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token, token_matches_user
from app.db.session import get_db
from app.models import AuthSession, User

bearer_scheme = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    """解析客户端 IP。

    只有直连对端属于 ``TRUSTED_PROXIES`` 时才采信 X-Forwarded-For，否则一律使用
    socket 层地址。否则任何人都能通过伪造该头绕过按 IP 的登录限流，并把审计 IP
    写成任意值。
    """
    peer = request.client.host if request.client else None
    if peer and settings.is_trusted_proxy(peer):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # 取最右侧非代理条目：左侧由客户端控制，右侧才是代理追加的真实来源。
            candidates = [item.strip() for item in forwarded.split(",") if item.strip()]
            for candidate in reversed(candidates):
                if not settings.is_trusted_proxy(candidate):
                    return candidate
            if candidates:
                return candidates[0]
    return peer or "unknown"


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get("qbot_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或凭证缺失")
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证无效或已过期")
    user = await db.scalar(select(User).where(User.username == payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    if not token_matches_user(payload, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证已失效，请重新登录")
    jti = payload.get("jti")
    if jti:
        session = await db.scalar(select(AuthSession).where(AuthSession.jti == jti, AuthSession.user_id == user.id))
        now = datetime.now(timezone.utc)
        expires_at = session.expires_at if session else None
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if not session or session.revoked_at or (expires_at and expires_at <= now):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录会话已失效，请重新登录")
        session.last_seen_at = now
        await db.commit()
    return user


def require(permission: str) -> Callable:
    async def _checker(user: User = Depends(get_current_user)) -> User:
        perms = user.permission_set
        if "*" in perms or permission in perms:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"缺少权限: {permission}")

    return _checker
