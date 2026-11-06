"""GitHub OAuth 授权：授权地址、state 签名、code 换 Token、用户仓库列表。

设计要点：
* **Client Secret 不出服务端**，只用于 code 换 token；数据库中的副本用 Fernet 加密。
* **state 用短期 JWT 签名**，不落库即可跨进程/多副本校验，附带 next 跳转目标并做开放重定向过滤。
* **Token 只在服务端加密存储**，接口只回显登录名/头像/授权范围，绝不返回明文。
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.http import new_client
from app.core.security import decrypt_secret, encrypt_secret
from app.models import GithubRepository, SystemSetting, User, UserGithubToken

logger = logging.getLogger("qbot.github.oauth")

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
STATE_PURPOSE = "github_oauth_state"
STATE_TTL_MINUTES = 10
SETTING_KEY = "github_oauth"
DEFAULT_NEXT = "/github"
MAX_REPOS_PER_PAGE = 100


class OAuthError(RuntimeError):
    """面向用户的 OAuth 失败原因（可直接展示在页面上）。"""


@dataclass(slots=True)
class OAuthApp:
    client_id: str
    client_secret: str
    scopes: str
    source: str  # database / env

    @property
    def masked_client_id(self) -> str:
        if len(self.client_id) <= 8:
            return "*" * len(self.client_id)
        return f"{self.client_id[:4]}{'*' * 8}{self.client_id[-4:]}"


# ---------------------------------------------------------------------------
# OAuth App 配置（数据库优先，环境变量兜底）
# ---------------------------------------------------------------------------
async def get_oauth_app(db: AsyncSession) -> OAuthApp | None:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == SETTING_KEY))
    if row and isinstance(row.value, dict):
        client_id = str(row.value.get("client_id") or "").strip()
        client_secret = decrypt_secret(row.value.get("client_secret_enc")) or ""
        if client_id and client_secret:
            scopes = str(row.value.get("scopes") or settings.github_oauth_scopes).strip()
            return OAuthApp(client_id, client_secret, scopes or settings.github_oauth_scopes, "database")
    if settings.github_oauth_client_id and settings.github_oauth_client_secret:
        return OAuthApp(
            settings.github_oauth_client_id.strip(),
            settings.github_oauth_client_secret.strip(),
            settings.github_oauth_scopes.strip() or "read:user repo",
            "env",
        )
    return None


async def save_oauth_app(
    db: AsyncSession, *, client_id: str, client_secret: str | None, scopes: str | None
) -> OAuthApp:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == SETTING_KEY))
    current = row.value if row and isinstance(row.value, dict) else {}
    # 前端只拿到打码后的 Client ID：留空表示「保持不变」，避免把掩码写回配置。
    client_id = (client_id or "").strip() or str(current.get("client_id") or "").strip()
    if not client_id:
        raise OAuthError("Client ID 不能为空")
    secret_enc = current.get("client_secret_enc")
    if client_secret:
        secret_enc = encrypt_secret(client_secret.strip())
    if not secret_enc:
        raise OAuthError("首次配置必须填写 Client Secret")
    value = {
        "client_id": client_id,
        "client_secret_enc": secret_enc,
        "scopes": (scopes or settings.github_oauth_scopes).strip() or "read:user repo",
    }
    if row:
        row.value = value
        row.description = "GitHub OAuth App 凭据（Client Secret 加密存储）"
        row.is_secret = True
    else:
        db.add(
            SystemSetting(
                key=SETTING_KEY,
                value=value,
                description="GitHub OAuth App 凭据（Client Secret 加密存储）",
                is_secret=True,
            )
        )
    await db.commit()
    app = await get_oauth_app(db)
    assert app is not None
    return app


def redirect_uri() -> str:
    configured = (settings.github_oauth_redirect_uri or "").strip()
    if configured:
        return configured
    # 默认指向前端站点（经 Nginx/Vite 同域代理 /api），回调后 302 /github 才能落回控制台页面；
    # 只有当前端与后端不同域时才需要显式配置 GITHUB_OAUTH_REDIRECT_URI。
    base = (settings.frontend_base_url or settings.public_base_url).rstrip("/")
    return f"{base}/api/github/oauth/callback"


# ---------------------------------------------------------------------------
# state 签名（防 CSRF / 开放重定向）
# ---------------------------------------------------------------------------
def sanitize_next(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate.startswith("/") or candidate.startswith("//") or "\\" in candidate:
        return DEFAULT_NEXT
    return candidate[:200]


def build_state(user: User, next_path: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "purpose": STATE_PURPOSE,
        "next": sanitize_next(next_path),
        "nonce": secrets.token_urlsafe(9),
        "iat": now,
        "exp": now + timedelta(minutes=STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def parse_state(state: str | None) -> dict[str, Any] | None:
    if not state:
        return None
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != STATE_PURPOSE or not payload.get("sub"):
        return None
    return payload


def authorize_url(app: OAuthApp, state: str, redirect: str | None = None) -> str:
    params = {
        "client_id": app.client_id,
        "redirect_uri": redirect or redirect_uri(),
        "scope": app.scopes,
        "state": state,
        "allow_signup": "false",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def append_query(path: str, **params: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}{urlencode(params)}"


# ---------------------------------------------------------------------------
# GitHub 侧调用
# ---------------------------------------------------------------------------
def _json_or_form(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    parsed = parse_qs(response.text or "")
    return {key: values[0] for key, values in parsed.items() if values}


def _api_headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "QBot-Platform",
    }


async def exchange_code(app: OAuthApp, code: str, redirect: str | None = None) -> dict[str, Any]:
    payload = {
        "client_id": app.client_id,
        "client_secret": app.client_secret,
        "code": code,
        "redirect_uri": redirect or redirect_uri(),
    }
    try:
        async with new_client(timeout=20.0) as client:
            response = await client.post(TOKEN_URL, data=payload, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthError(f"连接 GitHub 失败：{exc}") from exc
    data = _json_or_form(response)
    if response.status_code >= 400 or data.get("error"):
        detail = data.get("error_description") or data.get("error") or f"HTTP {response.status_code}"
        raise OAuthError(f"GitHub 拒绝授权：{detail}")
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise OAuthError("GitHub 未返回 access_token，请重新授权")
    return {
        "access_token": token,
        "token_type": str(data.get("token_type") or "bearer"),
        "scope": str(data.get("scope") or ""),
    }


async def fetch_github_user(token: str) -> dict[str, Any]:
    base = settings.github_api_base.rstrip("/")
    try:
        async with new_client(timeout=20.0) as client:
            response = await client.get(f"{base}/user", headers=_api_headers(token))
    except httpx.HTTPError as exc:
        raise OAuthError(f"读取 GitHub 账号失败：{exc}") from exc
    if response.status_code == 401:
        raise OAuthError("GitHub 授权已失效，请重新绑定")
    if response.status_code >= 400:
        raise OAuthError(f"读取 GitHub 账号失败（HTTP {response.status_code}）")
    data = response.json()
    if not data.get("id") or not data.get("login"):
        raise OAuthError("GitHub 返回的账号信息不完整")
    return {
        "id": int(data["id"]),
        "login": str(data["login"]),
        "name": data.get("name"),
        "avatar_url": data.get("avatar_url"),
        "email": data.get("email"),
        "scopes": response.headers.get("x-oauth-scopes") or "",
    }


async def list_user_repos(token: str, *, page: int = 1, per_page: int = MAX_REPOS_PER_PAGE) -> list[dict[str, Any]]:
    base = settings.github_api_base.rstrip("/")
    params = {
        "per_page": max(1, min(per_page, MAX_REPOS_PER_PAGE)),
        "page": max(1, page),
        "sort": "updated",
        "direction": "desc",
    }
    try:
        async with new_client(timeout=20.0) as client:
            response = await client.get(f"{base}/user/repos", headers=_api_headers(token), params=params)
    except httpx.HTTPError as exc:
        raise OAuthError(f"读取仓库列表失败：{exc}") from exc
    if response.status_code == 401:
        raise OAuthError("GitHub 授权已失效，请重新绑定")
    if response.status_code >= 400:
        raise OAuthError(f"读取仓库列表失败（HTTP {response.status_code}）：{response.text[:160]}")
    rows = response.json() or []
    result = []
    for item in rows:
        owner = (item.get("owner") or {}).get("login") or ""
        result.append(
            {
                "full_name": item.get("full_name") or f"{owner}/{item.get('name')}",
                "owner": owner,
                "name": item.get("name"),
                "private": bool(item.get("private")),
                "fork": bool(item.get("fork")),
                "archived": bool(item.get("archived")),
                "description": item.get("description"),
                "language": item.get("language"),
                "stars": int(item.get("stargazers_count") or 0),
                "html_url": item.get("html_url"),
                "updated_at": item.get("updated_at"),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Token 落库与取用
# ---------------------------------------------------------------------------
async def get_user_token(db: AsyncSession, user_id: int) -> UserGithubToken | None:
    return await db.scalar(select(UserGithubToken).where(UserGithubToken.user_id == user_id))


async def save_token(
    db: AsyncSession, user: User, token_payload: dict[str, Any], profile: dict[str, Any]
) -> UserGithubToken:
    github_id = int(profile["id"])
    conflict = await db.scalar(select(UserGithubToken).where(UserGithubToken.github_id == github_id))
    if conflict and conflict.user_id != user.id:
        raise OAuthError("该 GitHub 账号已绑定到其他平台用户，请先在对方账号下解绑")
    row = await db.scalar(select(UserGithubToken).where(UserGithubToken.user_id == user.id))
    if row is None:
        row = UserGithubToken(user_id=user.id, github_id=github_id, login=profile["login"], access_token_enc="-")
        db.add(row)
    row.github_id = github_id
    row.login = str(profile["login"])
    row.name = profile.get("name")
    row.avatar_url = profile.get("avatar_url")
    row.email = profile.get("email")
    row.scopes = token_payload.get("scope") or profile.get("scopes") or ""
    row.token_type = token_payload.get("token_type") or "bearer"
    row.access_token_enc = encrypt_secret(token_payload["access_token"]) or "-"
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise OAuthError("GitHub 账号绑定冲突，请刷新后重试") from exc
    await db.refresh(row)
    return row


async def delete_token(db: AsyncSession, user_id: int) -> bool:
    row = await get_user_token(db, user_id)
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def resolve_repo_token(db: AsyncSession, repo: GithubRepository) -> str | None:
    """仓库 API 调用凭据优先级：独立 PAT > 归属用户绑定的 OAuth Token > 全局环境变量。"""
    explicit = decrypt_secret(repo.token_enc)
    if explicit:
        return explicit
    if repo.owner_user_id:
        row = await get_user_token(db, repo.owner_user_id)
        if row:
            token = decrypt_secret(row.access_token_enc)
            if token:
                row.last_used_at = datetime.now(timezone.utc)
                return token
    return None


def profile_summary(row: UserGithubToken | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "login": row.login,
        "name": row.name,
        "avatar_url": row.avatar_url,
        "email": row.email,
        "scopes": row.scopes,
        "github_id": row.github_id,
        "last_used_at": row.last_used_at,
        "bound_at": row.created_at,
    }
