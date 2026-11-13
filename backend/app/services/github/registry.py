"""监控仓库的创建与归属判定（网页手动添加与 OAuth 批量导入共用）。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_secret
from app.models import GithubRepository, User
from app.services.github.monitor import import_repository_releases
from app.services.github.provider import build_repository_provider
from app.services.logs import write_log
from app.services.scheduler import scheduler_service

logger = logging.getLogger("qbot.github.registry")


class RepositoryExistsError(RuntimeError):
    """仓库已在监控列表中。"""


def is_super_admin(user: User) -> bool:
    return "*" in user.permission_set


def repo_scope_condition(user: User) -> Any | None:
    """普通用户只能看到自己添加的仓库与历史全局仓库；超级管理员不受限。"""
    if is_super_admin(user):
        return None
    return or_(GithubRepository.owner_user_id == user.id, GithubRepository.owner_user_id.is_(None))


def can_access_repo(user: User, repo: GithubRepository) -> bool:
    if is_super_admin(user):
        return True
    return repo.owner_user_id is None or repo.owner_user_id == user.id


async def create_monitored_repo(
    db: AsyncSession,
    *,
    provider: str,
    owner: str,
    name: str,
    token: str | None = None,
    webhook_secret: str | None = None,
    monitor_enabled: bool = True,
    poll_interval_seconds: int | None = None,
    notify_prerelease: bool = False,
    owner_user_id: int | None = None,
    persist_token: bool = True,
) -> tuple[GithubRepository, int]:
    """校验仓库可访问性、落库并导入历史版本（标记已通知，避免首次轮询轰炸群）。

    ``persist_token=False`` 用于 OAuth 导入：仓库不复制 Token，运行时按归属用户动态取用，
    用户重新授权或解绑后立即生效，避免出现两份互相漂移的凭据副本。
    """
    full_name = f"{owner}/{name}".lower()
    exists = await db.scalar(
        select(GithubRepository.id).where(func.lower(GithubRepository.full_name) == full_name)
    )
    if exists:
        raise RepositoryExistsError(f"{owner}/{name} 已在监控列表中")

    client = build_repository_provider(provider, token)
    info = await client.get_repo(owner, name)

    interval = poll_interval_seconds
    if interval is None:
        from app.services.settings_store import read_setting

        raw = await read_setting(db, "github_default_poll_seconds", 900)
        try:
            interval = int(raw)
        except (TypeError, ValueError):
            interval = 900
        interval = max(60, min(86400, interval))

    repo = GithubRepository(
        provider=provider,
        owner=info.get("owner", {}).get("login") or owner,
        name=info.get("name") or name,
        full_name=info.get("full_name") or f"{owner}/{name}",
        html_url=info.get("html_url")
        or f"https://{'gitee.com' if provider == 'gitee' else 'github.com'}/{owner}/{name}",
        description=info.get("description"),
        default_branch=info.get("default_branch"),
        language=info.get("language"),
        stars=int(info.get("stargazers_count") or 0),
        forks=int(info.get("forks_count") or 0),
        owner_user_id=owner_user_id,
        token_enc=encrypt_secret(token) if persist_token else None,
        webhook_secret_enc=encrypt_secret(webhook_secret),
        monitor_enabled=monitor_enabled,
        poll_interval_seconds=interval,
        notify_prerelease=notify_prerelease,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    imported = 0
    try:
        imported = await import_repository_releases(db, repo, client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("导入历史版本失败 %s: %s", repo.full_name, exc)
        await write_log(db, level="WARNING", category="github", message=f"导入历史版本失败：{exc}")
    scheduler_service.schedule_repo_poll(repo)
    return repo, imported
