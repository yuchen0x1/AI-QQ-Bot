"""GitHub 仓库监控、推送规则与推送记录 API。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.api.pagination import PageParam, PageSizeParam
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.session import get_db
from app.models import (
    Account,
    GithubRelease,
    GithubRepository,
    Group,
    PushRecord,
    PushRule,
    User,
)
from app.schemas.common import MessageOut, Page
from app.schemas.github import (
    CheckResult,
    PushRecordOut,
    PushRuleCreate,
    PushRuleOut,
    PushRuleUpdate,
    ReleaseOut,
    RepoCreate,
    RepoOut,
    RepoUpdate,
)
from app.services.github.client import GithubError
from app.services.github.provider import parse_repository_url
from app.services.github.monitor import check_repository
from app.services.github.notify import resend_record
from app.services.github.registry import (
    RepositoryExistsError,
    can_access_repo,
    create_monitored_repo,
    repo_scope_condition,
)
from app.services.logs import audit, write_log
from app.services.group_display import group_labels
from app.services.scheduler import scheduler_service

router = APIRouter(prefix="/github", tags=["GitHub监控"])


def serialize_repo(repo: GithubRepository, rules: int = 0, releases: int = 0, owner_name: str | None = None) -> RepoOut:
    return RepoOut(
        id=repo.id,
        provider=repo.provider,
        owner=repo.owner,
        name=repo.name,
        full_name=repo.full_name,
        html_url=repo.html_url,
        description=repo.description,
        default_branch=repo.default_branch,
        language=repo.language,
        stars=repo.stars,
        forks=repo.forks,
        owner_user_id=repo.owner_user_id,
        owner_username=owner_name,
        monitor_enabled=repo.monitor_enabled,
        remote_available=repo.remote_available,
        poll_interval_seconds=repo.poll_interval_seconds,
        notify_prerelease=repo.notify_prerelease,
        last_checked_at=repo.last_checked_at,
        last_check_status=repo.last_check_status,
        last_check_error=repo.last_check_error,
        last_release_tag=repo.last_release_tag,
        last_release_at=repo.last_release_at,
        last_webhook_at=repo.last_webhook_at,
        rule_count=rules,
        release_count=releases,
        has_token=bool(repo.token_enc),
        has_webhook_secret=bool(repo.webhook_secret_enc),
        monitor_activity=repo.monitor_activity,
        activity_initialized_at=repo.activity_initialized_at,
    )


async def _counts(db: AsyncSession) -> tuple[dict[int, int], dict[int, int]]:
    rule_counts = {
        rid: c
        for rid, c in (
            await db.execute(select(PushRule.repository_id, func.count(PushRule.id)).group_by(PushRule.repository_id))
        ).all()
    }
    release_counts = {
        rid: c
        for rid, c in (
            await db.execute(
                select(GithubRelease.repository_id, func.count(GithubRelease.id)).group_by(GithubRelease.repository_id)
            )
        ).all()
    }
    return rule_counts, release_counts


async def _owner_names(db: AsyncSession) -> dict[int, str]:
    return {row.id: row.username for row in await db.scalars(select(User))}


async def get_repo_or_403(db: AsyncSession, repo_id: int, user: User) -> GithubRepository:
    repo = await db.get(GithubRepository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if not can_access_repo(user, repo):
        raise HTTPException(status_code=403, detail="该仓库由其他用户添加，无权操作")
    return repo


def _parse_target(payload: RepoCreate) -> tuple[str, str, str]:
    provider_name = (payload.provider or "github").lower()
    if payload.url:
        try:
            detected_provider, owner, name = parse_repository_url(payload.url)
            if payload.provider == "github" and detected_provider != "github":
                provider_name = detected_provider
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        owner, name = (payload.owner or "").strip(), (payload.name or "").strip()
    if provider_name not in {"github", "gitee"}:
        raise HTTPException(status_code=400, detail="provider 仅支持 github 或 gitee")
    if not owner or not name:
        raise HTTPException(status_code=400, detail="仓库 owner / name 不能为空")
    return provider_name, owner, name


# ---------------------------------------------------------------------------
# 仓库
# ---------------------------------------------------------------------------
@router.get("/repos", response_model=list[RepoOut])
async def list_repos(include_unavailable: bool = False, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:view"))):
    query = select(GithubRepository)
    if not include_unavailable:
        query = query.where(GithubRepository.remote_available.is_(True))
    scope = repo_scope_condition(user)
    if scope is not None:
        query = query.where(scope)
    repos = list(await db.scalars(query.order_by(GithubRepository.id.desc())))
    rule_counts, release_counts = await _counts(db)
    owners = await _owner_names(db)
    return [
        serialize_repo(r, rule_counts.get(r.id, 0), release_counts.get(r.id, 0), owners.get(r.owner_user_id))
        for r in repos
    ]


@router.post("/repos", response_model=RepoOut, status_code=201)
async def add_repo(payload: RepoCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))):
    provider_name, owner, name = _parse_target(payload)
    try:
        repo, imported = await create_monitored_repo(
            db,
            provider=provider_name,
            owner=owner,
            name=name,
            token=payload.token,
            webhook_secret=payload.webhook_secret,
            monitor_enabled=payload.monitor_enabled,
            poll_interval_seconds=payload.poll_interval_seconds,
            notify_prerelease=payload.notify_prerelease,
            owner_user_id=user.id,
        )
    except RepositoryExistsError as exc:
        raise HTTPException(status_code=409, detail="该仓库已在监控列表中") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GithubError as exc:
        raise HTTPException(
            status_code=400, detail=f"无法访问该仓库：{exc}。请确认仓库地址正确，私有仓库需要提供具有 repo 权限的 Token"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"请求 GitHub 失败：{exc}") from exc

    await audit(db, user_id=user.id, username=user.username, action="add_repo", target=repo.full_name)
    await write_log(
        db,
        level="INFO",
        category="github",
        message=f"新增监控仓库 {repo.full_name}，导入历史版本 {imported} 个（不推送）",
    )
    rules, releases = await _counts(db)
    return serialize_repo(repo, rules.get(repo.id, 0), releases.get(repo.id, 0), user.username)


@router.put("/repos/{repo_id}", response_model=RepoOut)
async def update_repo(
    repo_id: int, payload: RepoUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))
):
    repo = await get_repo_or_403(db, repo_id, user)
    data = payload.model_dump(exclude_unset=True)
    token = data.pop("token", None)
    secret = data.pop("webhook_secret", None)
    if token is not None:
        repo.token_enc = encrypt_secret(token) if token else None
    if secret is not None:
        repo.webhook_secret_enc = encrypt_secret(secret) if secret else None
    for field, value in data.items():
        setattr(repo, field, value)
    await db.commit()
    await db.refresh(repo)
    scheduler_service.schedule_repo_poll(repo)
    await audit(db, user_id=user.id, username=user.username, action="update_repo", target=repo.full_name)
    rules, releases = await _counts(db)
    return serialize_repo(repo, rules.get(repo.id, 0), releases.get(repo.id, 0), (await _owner_names(db)).get(repo.owner_user_id))


@router.delete("/repos/{repo_id}", response_model=MessageOut)
async def delete_repo(repo_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))):
    repo = await get_repo_or_403(db, repo_id, user)
    name = repo.full_name
    scheduler_service.unschedule_repo(repo.id)
    await db.delete(repo)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="delete_repo", target=name)
    return MessageOut(detail=f"仓库 {name} 及其推送规则已删除")


@router.post("/repos/{repo_id}/check", response_model=CheckResult)
async def check_one(repo_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))):
    repo = await get_repo_or_403(db, repo_id, user)
    result = await check_repository(db, repo)
    return CheckResult(
        repository_id=repo.id,
        ok=bool(result.get("ok")),
        new_releases=int(result.get("new_releases") or 0),
        pushed=int(result.get("pushed") or 0),
        skipped=int(result.get("skipped") or 0),
        message=str(result.get("message") or ""),
        releases=result.get("releases") or [],
    )


@router.post("/repos/check-all", response_model=list[CheckResult])
async def check_all(db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))):
    query = select(GithubRepository)
    scope = repo_scope_condition(user)
    if scope is not None:
        query = query.where(scope)
    repos = list(await db.scalars(query))
    results = []
    for repo in repos:
        result = await check_repository(db, repo)
        results.append(
            CheckResult(
                repository_id=repo.id,
                ok=bool(result.get("ok")),
                new_releases=int(result.get("new_releases") or 0),
                pushed=int(result.get("pushed") or 0),
                skipped=int(result.get("skipped") or 0),
                message=str(result.get("message") or ""),
                releases=result.get("releases") or [],
            )
        )
    return results


@router.get("/repos/{repo_id}/releases", response_model=Page[ReleaseOut])
async def repo_releases(
    repo_id: int,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("github:view")),
):
    await get_repo_or_403(db, repo_id, user)
    query = select(GithubRelease).where(GithubRelease.repository_id == repo_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(
        query.order_by(GithubRelease.published_at.desc().nullslast(), GithubRelease.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(items=[ReleaseOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/repos/{repo_id}/webhook-info")
async def webhook_info(
    repo_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:view"))
):
    repo = await get_repo_or_403(db, repo_id, user)
    from app.core.config import settings

    return {
        "payload_url": f"{settings.public_base_url.rstrip('/')}/api/webhook/github/{repo.id}",
        "content_type": "application/json",
        "secret_masked": mask_secret(decrypt_secret(repo.webhook_secret_enc)),
        "has_secret": bool(repo.webhook_secret_enc),
        "events": ["release", "push", "issues", "pull_request", "issue_comment", "create", "delete", "star", "fork", "workflow_run"],
        "note": "在 GitHub 仓库 Settings → Webhooks 中添加该地址，内容类型选择 application/json，并填写相同的 Secret。",
    }


@router.post("/repos/{repo_id}/regenerate-secret")
async def regenerate_secret(
    repo_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))
):
    repo = await get_repo_or_403(db, repo_id, user)
    secret = secrets.token_urlsafe(32)
    repo.webhook_secret_enc = encrypt_secret(secret)
    await db.commit()
    return {"ok": True, "secret": secret, "message": "请立即把新 Secret 填入 GitHub Webhook 配置"}


# ---------------------------------------------------------------------------
# 推送规则
# ---------------------------------------------------------------------------
def serialize_rule(rule: PushRule, repo_name: str | None = None, account_name: str | None = None) -> PushRuleOut:
    data = PushRuleOut.model_validate(rule)
    data.repo_full_name = repo_name
    data.account_name = account_name
    return data


async def _rule_context(db: AsyncSession, rules: list[PushRule]) -> list[PushRuleOut]:
    repos = {r.id: r.full_name for r in await db.scalars(select(GithubRepository))}
    accounts = {a.id: a.name for a in await db.scalars(select(Account))}
    labels = await group_labels(db)
    result = []
    for rule in rules:
        item = serialize_rule(rule, repos.get(rule.repository_id), accounts.get(rule.account_id))
        item.qq_group_display = labels.get((rule.account_id, rule.qq_group), {}).get("number")
        result.append(item)
    return result


async def _visible_repo_ids(db: AsyncSession, user: User) -> set[int] | None:
    """返回当前用户可见的仓库 ID 集合；None 表示不受限（超级管理员）。"""
    scope = repo_scope_condition(user)
    if scope is None:
        return None
    return set(await db.scalars(select(GithubRepository.id).where(scope)))


@router.get("/push-rules", response_model=list[PushRuleOut])
async def list_rules(db: AsyncSession = Depends(get_db), user: User = Depends(require("push:view"))):
    query = select(PushRule)
    allowed = await _visible_repo_ids(db, user)
    if allowed is not None:
        query = query.where(PushRule.repository_id.in_(allowed or {-1}))
    rules = list(await db.scalars(query.order_by(PushRule.id.desc())))
    return await _rule_context(db, rules)


@router.post("/push-rules", response_model=PushRuleOut, status_code=201)
async def create_rule(
    payload: PushRuleCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))
):
    repo = await get_repo_or_403(db, payload.repository_id, user)
    account = await db.get(Account, payload.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="QQ 账号不存在")
    rule = PushRule(**payload.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await audit(
        db, user_id=user.id, username=user.username, action="create_push_rule", target=f"{repo.full_name}->{rule.qq_group}"
    )
    return serialize_rule(rule, repo.full_name, account.name)


@router.put("/push-rules/{rule_id}", response_model=PushRuleOut)
async def update_rule(
    rule_id: int, payload: PushRuleUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))
):
    rule = await db.get(PushRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="推送规则不存在")
    await get_repo_or_403(db, rule.repository_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "account_id" in data:
        account = await db.get(Account, data["account_id"])
        if not account:
            raise HTTPException(status_code=404, detail="QQ 账号不存在")
    for field, value in data.items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    repo = await db.get(GithubRepository, rule.repository_id)
    account = await db.get(Account, rule.account_id)
    await audit(db, user_id=user.id, username=user.username, action="update_push_rule", target=str(rule.id))
    return serialize_rule(rule, repo.full_name if repo else None, account.name if account else None)


@router.delete("/push-rules/{rule_id}", response_model=MessageOut)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    rule = await db.get(PushRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="推送规则不存在")
    await get_repo_or_403(db, rule.repository_id, user)
    await db.delete(rule)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="delete_push_rule", target=str(rule_id))
    return MessageOut(detail="推送规则已删除")


# ---------------------------------------------------------------------------
# 推送记录
# ---------------------------------------------------------------------------
@router.get("/push-records", response_model=Page[PushRecordOut])
async def list_push_records(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    status: str | None = None,
    repo_id: int | None = None,
    qq_group: int | None = None,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("push:view")),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = select(PushRecord).where(PushRecord.created_at >= since)
    allowed = await _visible_repo_ids(db, user)
    if allowed is not None:
        query = query.where(PushRecord.repository_id.in_(allowed or {-1}))
    if status:
        query = query.where(PushRecord.status == status)
    if repo_id:
        query = query.where(PushRecord.repository_id == repo_id)
    if qq_group:
        matching_groups = select(Group.account_id, Group.group_number).where(Group.display_number == str(qq_group))
        query = query.where(or_(PushRecord.qq_group == qq_group,
                                tuple_(PushRecord.account_id, PushRecord.qq_group).in_(matching_groups)))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(await db.scalars(query.order_by(PushRecord.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    repos = {r.id: r.full_name for r in await db.scalars(select(GithubRepository))}
    items = []
    labels = await group_labels(db)
    for record in rows:
        data = PushRecordOut.model_validate(record)
        data.repo_full_name = repos.get(record.repository_id)
        data.qq_group_display = labels.get((record.account_id, record.qq_group), {}).get("number")
        items.append(data)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/push-records/{record_id}/retry")
async def retry_push(record_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("push:manage"))):
    record = await db.get(PushRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="推送记录不存在")
    await get_repo_or_403(db, record.repository_id, user)
    updated = await resend_record(db, record)
    await audit(db, user_id=user.id, username=user.username, action="retry_push", target=str(record_id))
    return {
        "ok": updated.status == "success",
        "status": updated.status,
        "message": "重新推送成功" if updated.status == "success" else f"重新推送失败：{updated.error}",
    }
