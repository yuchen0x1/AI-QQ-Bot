"""认证、用户与角色管理。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_current_user, require
from app.core.config import settings
from app.core.ratelimit import login_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import AuditLog, GithubRepository, LoginAttempt, Role, User
from app.schemas.auth import (
    AuditLogOut,
    LoginRequest,
    PasswordChange,
    RoleOut,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import MessageOut, Page
from app.services.logs import audit, write_log

router = APIRouter(tags=["认证"])


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
    db.add(LoginAttempt(username=payload.username, ip=ip, success=True))
    await db.commit()
    await db.refresh(user)

    token = create_access_token(
        user.username,
        {"role": user.role.name if user.role else "viewer"},
        password_hash=user.password_hash,
    )
    response.set_cookie(
        "qbot_token",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.access_token_expire_minutes * 60,
    )
    await audit(db, user_id=user.id, username=user.username, action="login", ip=ip)
    return TokenOut(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/auth/logout", response_model=MessageOut)
async def logout(response: Response):
    response.delete_cookie("qbot_token")
    return MessageOut(detail="已退出登录")


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/auth/password", response_model=MessageOut)
async def change_password(
    payload: PasswordChange, request: Request, response: Response, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    # 签发包含最新密码 hash 的新 token 写回 Cookie，确保当前会话平滑过渡同时作废其它会话
    new_token = create_access_token(
        user.username,
        {"role": user.role.name if user.role else "viewer"},
        password_hash=user.password_hash,
    )
    response.set_cookie(
        "qbot_token",
        new_token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.access_token_expire_minutes * 60,
    )
    await audit(db, user_id=user.id, username=user.username, action="change_password", ip=client_ip(request))
    return MessageOut(detail="密码已更新")


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db), _: User = Depends(require("user:manage"))):
    return list(await db.scalars(select(Role).order_by(Role.id)))


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    page: int = 1,
    page_size: int = 20,
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
    page: int = 1,
    page_size: int = 20,
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
