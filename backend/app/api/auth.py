"""认证、用户与角色管理。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_current_user, require
from app.api.pagination import PageParam, PageSizeParam
from app.core.config import settings
from app.core.ratelimit import login_limiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    password_needs_rehash,
    token_matches_user,
    verify_password,
)
from app.core.totp import generate_secret, matching_counter, provisioning_uri
from app.db.session import get_db
from app.models import AuditLog, AuthSession, GithubRepository, LoginAttempt, Role, User
from app.schemas.auth import (
    AuditLogOut,
    LoginRequest,
    PasswordChange,
    PasswordChangeOut,
    RoleOut,
    SessionOut,
    TokenOut,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorSetupOut,
    TwoFactorVerifyRequest,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import MessageOut, Page
from app.services.logs import audit, write_log

router = APIRouter(tags=["认证"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent", "").strip()
    return value[:500] or None


async def _issue_token(db: AsyncSession, user: User, request: Request) -> tuple[str, int]:
    expires_in = settings.access_token_expire_minutes * 60
    token = create_access_token(
        user.username,
        {"role": user.role.name if user.role else "viewer"},
        password_hash=user.password_hash,
    )
    decoded = decode_access_token(token)
    if not decoded or not decoded.get("jti"):
        raise HTTPException(status_code=500, detail="无法创建登录会话")
    db.add(
        AuthSession(
            user_id=user.id,
            jti=decoded["jti"],
            ip=client_ip(request),
            user_agent=_session_user_agent(request),
            expires_at=datetime.fromtimestamp(decoded["exp"], tz=timezone.utc),
            last_seen_at=_now(),
        )
    )
    return token, expires_in


async def _token_response(db: AsyncSession, user: User, request: Request, response: Response) -> TokenOut:
    token, expires_in = await _issue_token(db, user, request)
    response.set_cookie(
        "qbot_token",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=expires_in,
    )
    return TokenOut(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    allowed, retry_after = login_limiter.allow(f"{payload.username}:{ip}")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"登录尝试过于频繁，请 {retry_after} 秒后再试")

    user = await db.scalar(select(User).where(User.username == payload.username))
    if user and user.is_locked:
        remaining = int((user.locked_until.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds())
        raise HTTPException(status_code=423, detail=f"账号已锁定，请 {max(1, remaining // 60)} 分钟后再试")

    if not user or not verify_password(payload.password, user.password_hash):
        if user:
            user.failed_attempts += 1
            if user.failed_attempts >= settings.login_max_attempts:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.login_lock_minutes)
                user.failed_attempts = 0
                await write_log(
                    db,
                    level="WARNING",
                    category="auth",
                    message=f"用户 {payload.username} 连续登录失败，已锁定 {settings.login_lock_minutes} 分钟",
                )
            await db.commit()
        db.add(LoginAttempt(username=payload.username, ip=ip, success=False))
        await db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip
    if password_needs_rehash(user.password_hash):
        # 旧格式哈希（未做 SHA-256 预哈希）在登录成功时就地升级，用户无感知。
        user.password_hash = hash_password(payload.password)
    db.add(LoginAttempt(username=payload.username, ip=ip, success=True))
    await db.commit()
    await db.refresh(user)

    if user.totp_enabled:
        user.totp_challenge_nonce = secrets.token_urlsafe(32)
        await db.commit()
        challenge = create_access_token(
            user.username,
            {"purpose": "2fa_challenge", "nonce": user.totp_challenge_nonce},
            expires_minutes=5,
            password_hash=user.password_hash,
        )
        await audit(db, user_id=user.id, username=user.username, action="login_2fa_required", ip=ip)
        return TokenOut(
            expires_in=300,
            requires_2fa=True,
            challenge_token=challenge,
        )

    token_response = await _token_response(db, user, request, response)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="login", ip=ip)
    return token_response


@router.post("/auth/login/2fa", response_model=TokenOut)
async def verify_login_2fa(
    payload: TwoFactorVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    allowed, retry_after = login_limiter.allow(f"2fa:{payload.challenge_token}:{client_ip(request)}")
    if not allowed:
        raise HTTPException(status_code=429, detail=f"验证码尝试过于频繁，请 {retry_after} 秒后再试")
    decoded = decode_access_token(payload.challenge_token)
    if not decoded or decoded.get("purpose") != "2fa_challenge" or not decoded.get("sub"):
        raise HTTPException(status_code=401, detail="二次验证已过期，请重新登录")
    user = await db.scalar(select(User).where(User.username == decoded["sub"]))
    if not user or not user.is_active or not token_matches_user(decoded, user.password_hash) or not user.totp_enabled or decoded.get("nonce") != user.totp_challenge_nonce:
        raise HTTPException(status_code=401, detail="二次验证已失效，请重新登录")
    secret = decrypt_secret(user.totp_secret_enc)
    counter = matching_counter(secret or "", payload.code)
    if counter is None or (user.totp_last_counter is not None and counter <= user.totp_last_counter):
        raise HTTPException(status_code=401, detail="验证码错误或已使用")
    user.totp_last_counter = counter
    user.totp_challenge_nonce = None
    token_response = await _token_response(db, user, request, response)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="login_2fa", ip=client_ip(request))
    return token_response


@router.post("/auth/logout", response_model=MessageOut)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    token = request.headers.get("authorization", "")
    raw_token = token[7:] if token.lower().startswith("bearer ") else request.cookies.get("qbot_token")
    if raw_token:
        decoded = decode_access_token(raw_token)
        jti = decoded.get("jti") if decoded else None
        if jti:
            session = await db.scalar(select(AuthSession).where(AuthSession.jti == jti))
            if session and not session.revoked_at:
                session.revoked_at = _now()
                await db.commit()
    response.delete_cookie("qbot_token")
    return MessageOut(detail="已退出登录")


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.get("/auth/2fa", response_model=TwoFactorSetupOut)
async def two_factor_status(user: User = Depends(get_current_user)):
    return TwoFactorSetupOut(enabled=user.totp_enabled)


@router.post("/auth/2fa/setup", response_model=TwoFactorSetupOut)
async def two_factor_setup(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="两步验证已启用，请先关闭后再重新绑定")
    secret = generate_secret()
    user.totp_secret_enc = encrypt_secret(secret)
    user.totp_enabled = False
    user.totp_last_counter = None
    await db.commit()
    return TwoFactorSetupOut(
        enabled=False,
        secret=secret,
        provisioning_uri=provisioning_uri(secret, user.username, settings.app_name),
    )


@router.post("/auth/2fa/confirm", response_model=TwoFactorSetupOut)
async def two_factor_confirm(
    payload: TwoFactorConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="两步验证已启用")
    secret = decrypt_secret(user.totp_secret_enc)
    counter = matching_counter(secret or "", payload.code)
    if counter is None:
        raise HTTPException(status_code=400, detail="验证码错误，请确认设备时间同步后重试")
    user.totp_enabled = True
    user.totp_last_counter = None
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="enable_2fa", ip=client_ip(request))
    return TwoFactorSetupOut(enabled=True)


@router.post("/auth/2fa/disable", response_model=TwoFactorSetupOut)
async def two_factor_disable(
    payload: TwoFactorDisableRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码不正确")
    secret = decrypt_secret(user.totp_secret_enc)
    counter = matching_counter(secret or "", payload.code)
    if counter is None:
        raise HTTPException(status_code=400, detail="验证码错误")
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_counter = None
    user.totp_challenge_nonce = None
    await db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=_now()))
    await db.commit()
    response.delete_cookie("qbot_token")
    await audit(db, user_id=user.id, username=user.username, action="disable_2fa", ip=client_ip(request))
    return TwoFactorSetupOut(enabled=False)


@router.get("/auth/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    current_token = request.headers.get("authorization", "")
    raw_token = current_token[7:] if current_token.lower().startswith("bearer ") else request.cookies.get("qbot_token")
    current_jti = (decode_access_token(raw_token) or {}).get("jti") if raw_token else None
    now = _now()
    rows = await db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.last_seen_at.desc())
    )
    result = []
    for row in rows:
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            continue
        result.append(
            SessionOut(
                id=row.id,
                ip=row.ip,
                user_agent=row.user_agent,
                expires_at=expires_at,
                last_seen_at=row.last_seen_at,
                created_at=row.created_at,
                revoked_at=row.revoked_at,
                current=row.jti == current_jti,
            )
        )
    return result


@router.delete("/auth/sessions/{session_id}", response_model=MessageOut)
async def revoke_session(
    session_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id))
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    current_token = request.headers.get("authorization", "")
    raw_token = current_token[7:] if current_token.lower().startswith("bearer ") else request.cookies.get("qbot_token")
    if raw_token and (decode_access_token(raw_token) or {}).get("jti") == row.jti:
        raise HTTPException(status_code=400, detail="不能撤销当前会话，请使用退出登录")
    row.revoked_at = _now()
    await db.commit()
    return MessageOut(detail="会话已撤销")


@router.post("/auth/sessions/revoke-others", response_model=MessageOut)
async def revoke_other_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    current_token = request.headers.get("authorization", "")
    raw_token = current_token[7:] if current_token.lower().startswith("bearer ") else request.cookies.get("qbot_token")
    current_jti = (decode_access_token(raw_token) or {}).get("jti") if raw_token else None
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.jti != current_jti, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
    return MessageOut(detail="其它登录会话已撤销")


@router.post("/auth/password", response_model=PasswordChangeOut)
async def change_password(
    payload: PasswordChange, request: Request, response: Response, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    await db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=_now()))
    await db.commit()
    # 签发包含最新密码 hash 的新 token 写回 Cookie，确保当前会话平滑过渡同时作废其它会话
    new_token, expires_in = await _issue_token(db, user, request)
    response.set_cookie(
        "qbot_token",
        new_token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=expires_in,
    )
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="change_password", ip=client_ip(request))
    return PasswordChangeOut(detail="密码已更新", access_token=new_token, expires_in=expires_in)


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db), _: User = Depends(require("user:manage"))):
    return list(await db.scalars(select(Role).order_by(Role.id)))


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("user:manage")),
):
    query = select(User)
    if keyword:
        query = query.where(User.username.ilike(f"%{keyword}%"))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(User.id).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[UserOut.model_validate(u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require("user:manage")),
):
    exists = await db.scalar(select(User).where(User.username == payload.username))
    if exists:
        raise HTTPException(status_code=409, detail="用户名已存在")
    role_id = payload.role_id
    if role_id is None:
        role = await db.scalar(select(Role).where(Role.name == "viewer"))
        role_id = role.id if role else None
    user = User(
        username=payload.username,
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role_id=role_id,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit(
        db, user_id=current.id, username=current.username, action="create_user", target=user.username, ip=client_ip(request)
    )
    return UserOut.model_validate(user)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require("user:manage")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "password":
            if value:
                user.password_hash = hash_password(value)
                await db.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=_now())
                )
            continue
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    await audit(db, user_id=current.id, username=current.username, action="update_user", target=user.username, ip=client_ip(request))
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", response_model=MessageOut)
async def delete_user(
    user_id: int, request: Request, db: AsyncSession = Depends(get_db), current: User = Depends(require("user:manage"))
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    # 仓库归属为软引用：删除用户时把其名下仓库转为全局仓库，避免留下悬空 ID。
    await db.execute(
        update(GithubRepository).where(GithubRepository.owner_user_id == user.id).values(owner_user_id=None)
    )
    await db.delete(user)
    await db.commit()
    await audit(db, user_id=current.id, username=current.username, action="delete_user", target=str(user_id), ip=client_ip(request))
    return MessageOut(detail="用户已删除")


@router.get("/audit-logs", response_model=Page[AuditLogOut])
async def list_audit_logs(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    action: str | None = None,
    username: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("audit:view")),
):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
    if username:
        query = query.where(AuditLog.username.ilike(f"%{username}%"))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[AuditLogOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)
