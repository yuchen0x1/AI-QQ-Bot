"""GitHub 仓库监控：拉取仓库信息、解析 Release / Tag、事件去重、触发推送。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GithubEvent, GithubRelease, GithubRepository
from app.services.github.client import GithubClient, GithubError
from app.services.github.oauth import resolve_repo_token
from app.services.github.provider import build_repository_provider
from app.services.github.notify import dispatch_release
from app.services.logs import write_log

logger = logging.getLogger("qbot.github.monitor")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _assets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for asset in payload.get("assets") or []:
        result.append(
            {
                "name": asset.get("name"),
                "size": asset.get("size"),
                "download_count": asset.get("download_count"),
                "content_type": asset.get("content_type"),
                "browser_download_url": asset.get("browser_download_url"),
            }
        )
    return result


def _release_from_payload(repo: GithubRepository, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag_name": payload.get("tag_name") or payload.get("name") or "unknown",
        "name": payload.get("name"),
        "body": payload.get("body"),
        "html_url": payload.get("html_url") or f"{repo.html_url}/releases",
        "prerelease": bool(payload.get("prerelease")),
        "draft": bool(payload.get("draft")),
        "assets": _assets(payload),
        "published_at": _parse_dt(payload.get("published_at") or payload.get("created_at")),
    }


async def upsert_release(
    db: AsyncSession, repo: GithubRepository, data: dict[str, Any], *, mark_notified: bool = False
) -> tuple[GithubRelease, bool]:
    """返回 (release, 是否新建)。"""
    tag = str(data["tag_name"])
    release = await db.scalar(
        select(GithubRelease).where(GithubRelease.repository_id == repo.id, GithubRelease.tag_name == tag)
    )
    if release:
        changed = False
        for field in ("name", "body", "html_url", "prerelease", "draft", "assets", "published_at"):
            value = data.get(field)
            if value is not None and getattr(release, field) != value:
                setattr(release, field, value)
                changed = True
        if changed:
            await db.commit()
        return release, False
    release = GithubRelease(
        repository_id=repo.id,
        tag_name=tag,
        name=data.get("name"),
        body=data.get("body"),
        html_url=data.get("html_url"),
        prerelease=bool(data.get("prerelease")),
        draft=bool(data.get("draft")),
        assets=data.get("assets") or [],
        published_at=data.get("published_at"),
        notified=mark_notified,
    )
    db.add(release)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        release = await db.scalar(
            select(GithubRelease).where(GithubRelease.repository_id == repo.id, GithubRelease.tag_name == tag)
        )
        assert release is not None
        return release, False
    await db.refresh(release)
    return release, True


async def _register_event(db: AsyncSession, repo: GithubRepository, release: GithubRelease, source: str) -> bool:
    key = f"release:{repo.id}:{release.tag_name}"
    exists = await db.scalar(select(GithubEvent.id).where(GithubEvent.dedupe_key == key))
    if exists:
        return False
    db.add(
        GithubEvent(
            repository_id=repo.id,
            event_type="release",
            action="published",
            dedupe_key=key,
            source=source,
            payload={"tag": release.tag_name, "html_url": release.html_url},
            release_id=release.id,
            processed=True,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False
    return True


async def sync_releases(
    db: AsyncSession,
    repo: GithubRepository,
    client: GithubClient,
    *,
    notify: bool = True,
    mark_notified: bool = False,
) -> list[GithubRelease]:
    new_releases: list[GithubRelease] = []
    try:
        payloads = await client.list_releases(repo.owner, repo.name)
    except GithubError as exc:
        if exc.status_code == 404:
            raise
        payloads = []
    if not payloads and not repo.monitor_activity:
        tags = await client.list_tags(repo.owner, repo.name)
        payloads = [
            {
                "tag_name": tag.get("name"),
                "name": tag.get("name"),
                "body": None,
                "html_url": f"{repo.html_url}/releases/tag/{tag.get('name')}",
                "prerelease": False,
                "draft": False,
                "assets": [],
                "published_at": None,
            }
            for tag in tags[:10]
        ]
        if payloads:
            await write_log(
                db,
                level="INFO",
                category="github",
                message=f"{repo.full_name} 没有 Release，回退到 Tag 检测（{len(payloads)} 个标签）",
            )
    for payload in payloads:
        if not payload.get("tag_name"):
            continue
        if payload.get("draft"):
            continue
        if repo.notify_prerelease is False and payload.get("prerelease") and not mark_notified:
            pass  # 仍入库，只是按推送规则决定是否推送
        data = _release_from_payload(repo, payload)
        release, is_new = await upsert_release(db, repo, data, mark_notified=mark_notified)
        if is_new and not mark_notified:
            new_releases.append(release)
    new_releases.sort(key=lambda r: (r.published_at or datetime.min.replace(tzinfo=timezone.utc), r.id))

    for release in new_releases:
        await _register_event(db, repo, release, source="poll")
        if notify:
            await dispatch_release(db, repo, release, source="poll")

    latest = new_releases[-1] if new_releases else None
    if not latest:
        latest = await db.scalar(
            select(GithubRelease)
            .where(GithubRelease.repository_id == repo.id)
            .order_by(GithubRelease.published_at.desc().nullslast(), GithubRelease.id.desc())
            .limit(1)
        )
    if latest:
        repo.last_release_tag = latest.tag_name
        repo.last_release_at = latest.published_at or latest.detected_at
    await db.commit()
    return new_releases


async def check_repository(
    db: AsyncSession, repo: GithubRepository, *, notify: bool = True, client: GithubClient | None = None
) -> dict[str, Any]:
    client = client or build_repository_provider(repo.provider, await resolve_repo_token(db, repo))
    result: dict[str, Any] = {
        "repository_id": repo.id,
        "repository": repo.full_name,
        "ok": False,
        "new_releases": 0,
        "pushed": 0,
        "skipped": 0,
        "message": "",
        "releases": [],
    }
    try:
        info = await client.get_repo(repo.owner, repo.name)
        repo.description = info.get("description") or repo.description
        repo.default_branch = info.get("default_branch") or repo.default_branch
        repo.language = info.get("language") or repo.language
        repo.stars = int(info.get("stargazers_count") or 0)
        repo.forks = int(info.get("forks_count") or 0)
        repo.html_url = info.get("html_url") or repo.html_url
        repo.last_checked_at = datetime.now(timezone.utc)
        repo.last_check_status = "ok"
        repo.last_check_error = None
        await db.commit()

        new_releases = await sync_releases(db, repo, client, notify=notify)
        result["new_releases"] = len(new_releases)
        result["releases"] = [r.tag_name for r in new_releases]
        if notify and new_releases:
            from app.models import PushRecord

            push_rows = await db.scalars(
                select(PushRecord).where(
                    PushRecord.repository_id == repo.id,
                    PushRecord.release_id.in_([release.id for release in new_releases]),
                )
            )
            records = list(push_rows)
            result["pushed"] = sum(1 for row in records if row.status == "success")
            result["skipped"] = sum(1 for row in records if row.status == "skipped")
        if repo.provider == "github" and repo.monitor_activity:
            from app.services.github.activity import sync_activity

            activity = await sync_activity(db, repo, client, notify=notify)
            result["new_events"] = activity["new_events"]
            result["pushed"] += activity["pushed"]
            result["warning"] = activity["warning"]
        result["ok"] = True
        result["message"] = f"检查完成，发现 {len(new_releases)} 个新版本、{result.get('new_events', 0)} 条新动态"
        if new_releases:
            await write_log(
                db,
                level="INFO",
                category="github",
                message=f"{repo.full_name} 检测到新版本：{', '.join(result['releases'])}",
                context={"repo": repo.full_name},
            )
    except Exception as exc:  # noqa: BLE001
        repo.last_checked_at = datetime.now(timezone.utc)
        repo.last_check_status = "error"
        repo.last_check_error = str(exc)[:500]
        await db.commit()
        result["message"] = str(exc)
        await write_log(
            db,
            level="ERROR",
            category="github",
            message=f"检查仓库 {repo.full_name} 失败：{exc}",
        )
    return result


async def check_all_repositories(db: AsyncSession, *, only_enabled: bool = True) -> list[dict[str, Any]]:
    query = select(GithubRepository)
    if only_enabled:
        query = query.where(GithubRepository.monitor_enabled.is_(True))
    repos = list(await db.scalars(query.order_by(GithubRepository.id)))
    results = []
    for repo in repos:
        results.append(await check_repository(db, repo))
    return results


async def import_repository_releases(
    db: AsyncSession, repo: GithubRepository, client: GithubClient | None = None
) -> int:
    """添加仓库时导入历史版本，避免把旧版本当成新版本推送。"""
    client = client or build_repository_provider(repo.provider, await resolve_repo_token(db, repo))
    releases = await sync_releases(db, repo, client, notify=False, mark_notified=True)
    return len(releases)


async def handle_webhook_payload(
    db: AsyncSession,
    repo: GithubRepository,
    payload: dict[str, Any],
    *,
    delivery_id: str | None = None,
    event_type: str = "release",
) -> dict[str, Any]:
    """处理 GitHub Webhook 事件：验签已在路由层完成。"""
    if event_type == "repository" and payload.get("action") in {"deleted", "transferred"}:
        from app.services.github.automation import reconcile_rules
        from app.services.scheduler import scheduler_service
        repo.remote_available = False
        repo.last_check_status = "unavailable"
        repo.last_check_error = "GitHub 已通知仓库删除或转移，历史保留"
        await db.commit()
        scheduler_service.unschedule_repo(repo.id)
        if repo.owner_user_id:
            await reconcile_rules(db, repo.owner_user_id)
        return {"ok": True, "new_releases": 0, "message": "已停止不可访问仓库的监控，历史保留"}
    if not repo.monitor_enabled:
        return {"ok": True, "message": "仓库监控已暂停", "new_releases": 0}
    if event_type != "release" or payload.get("action") not in {"published", "released", "updated", "created"}:
        if repo.monitor_activity:
            from app.services.github.activity import ingest_activity

            return await ingest_activity(db, repo, event_type, {**payload, "_delivery_id": delivery_id}, source="webhook")
        return {"ok": True, "message": "该仓库仅监控版本发布", "new_releases": 0}
    if (payload.get("release") or {}).get("draft"):
        return {"ok": True, "message": "草稿版本不发送通知", "new_releases": 0}
    if event_type not in {"release", "push", "create"}:
        return {"ok": True, "message": f"忽略事件类型 {event_type}", "new_releases": 0}
    if event_type == "release":
        release_payload = payload.get("release") or {}
        if payload.get("action") not in {"published", "released", "updated", "created"}:
            return {"ok": True, "message": f"忽略 release action={payload.get('action')}", "new_releases": 0}
        tag = release_payload.get("tag_name")
        if not tag:
            return {"ok": False, "message": "release 事件缺少 tag_name", "new_releases": 0}
        key = f"webhook:{repo.id}:{tag}:{payload.get('action')}"
        if delivery_id:
            key = f"webhook:{repo.id}:{delivery_id}"
        exists = await db.scalar(select(GithubEvent.id).where(GithubEvent.dedupe_key == key))
        if exists:
            return {"ok": True, "message": "重复事件已忽略", "new_releases": 0, "duplicate": True}
        data = _release_from_payload(repo, release_payload)
        release, is_new = await upsert_release(db, repo, data)
        db.add(
            GithubEvent(
                repository_id=repo.id,
                event_type=event_type,
                action=payload.get("action"),
                dedupe_key=key,
                source="webhook",
                payload={"tag": tag, "action": payload.get("action")},
                release_id=release.id,
                processed=True,
            )
        )
        repo.last_webhook_at = datetime.now(timezone.utc)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return {"ok": True, "message": "重复事件已忽略", "new_releases": 0, "duplicate": True}
        repo.last_release_tag = release.tag_name
        repo.last_release_at = release.published_at or datetime.now(timezone.utc)
        await db.commit()
        records = await dispatch_release(db, repo, release, source="webhook")
        await write_log(
            db,
            level="INFO",
            category="github",
            message=f"收到 Webhook：{repo.full_name} {release.tag_name}，推送 {len(records)} 条"
            + ("" if is_new else "（版本已存在，按规则补推）"),
            context={"repo": repo.full_name, "delivery": delivery_id},
        )
        return {
            "ok": True,
            "message": f"已处理 {repo.full_name} {release.tag_name}",
            "new_releases": 1 if is_new else 0,
            "pushed": len([r for r in records if r.status == "success"]),
        }
    return {"ok": True, "message": "事件已记录", "new_releases": 0}
