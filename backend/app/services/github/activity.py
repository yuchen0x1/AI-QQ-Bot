"""Repository activity normalization, durable deduplication and QQ delivery."""

from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GithubEvent, GithubRepository, PushRecord, PushRule
from app.schemas.github import ACTIVITY_TYPES
from app.services.github.card import send_push_record
from app.services.templates import strip_markdown, truncate

EVENT_LABELS = {
    "push": "代码提交", "release": "版本发布", "issues": "Issue 动态", "pull_request": "PR 动态",
    "issue_comment": "Issue / PR 评论", "pull_request_review": "PR 审核", "pull_request_review_comment": "代码评论",
    "create": "创建分支 / 标签", "delete": "删除分支 / 标签", "star": "Star 动态", "fork": "Fork 动态",
    "workflow_run": "Actions 运行", "discussion": "讨论动态", "discussion_comment": "讨论评论",
    "public": "仓库公开", "repository": "仓库变更", "gollum": "Wiki 更新", "member": "协作者变更",
}
POLL_TYPES = {
    "PushEvent": "push", "IssuesEvent": "issues", "PullRequestEvent": "pull_request", "IssueCommentEvent": "issue_comment",
    "PullRequestReviewEvent": "pull_request_review", "PullRequestReviewCommentEvent": "pull_request_review_comment",
    "CreateEvent": "create", "DeleteEvent": "delete", "WatchEvent": "star", "ForkEvent": "fork",
    "PublicEvent": "public", "GollumEvent": "gollum", "MemberEvent": "member",
    "DiscussionEvent": "discussion",
}
ACTION_LABELS = {"opened": "新建", "closed": "关闭", "reopened": "重新打开", "edited": "编辑", "created": "新增",
                 "deleted": "删除", "published": "发布", "submitted": "提交审核", "synchronize": "更新提交",
                 "labeled": "添加标签", "unlabeled": "移除标签", "assigned": "分配处理人", "completed": "运行完成",
                 "started": "新增", "released": "发布", "updated": "更新", "unpublished": "撤销发布"}

# 这些事件在 GitHub 侧没有跨通道共用的稳定 ID：Webhook 给的是 delivery UUID，
# Events API 给的是事件流水号，同一次 Star/Fork 经两条通道到达时两者必然不同。
# 因此它们的去重键只由「谁 + 做了什么 + 作用对象 + 事件日期」构造，见 _channel_agnostic_identity。
CHANNEL_AGNOSTIC_TYPES = {"star", "fork", "public", "gollum", "member", "repository"}


def _event_day(payload: dict[str, Any]) -> str:
    """事件发生的 UTC 日期；两条通道指向同一次事件时取值一致，可安全进去重键。"""
    for value in (
        payload.get("_occurred_at"),
        payload.get("starred_at"),
        payload.get("created_at"),
        (payload.get("forkee") or {}).get("created_at") if isinstance(payload.get("forkee"), dict) else None,
    ):
        parsed = _parse_event_time(value)
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")
    # Webhook 的多数事件不带时间戳，退化为收件日期：与轮询路径的事件日期通常是同一天。
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _channel_agnostic_identity(event_type: str, actor: str, action: str, payload: dict[str, Any]) -> list[str]:
    subject = ""
    if event_type == "fork":
        forkee = payload.get("forkee") if isinstance(payload.get("forkee"), dict) else {}
        subject = str(forkee.get("full_name") or forkee.get("id") or "")
    elif event_type == "member":
        member = payload.get("member") if isinstance(payload.get("member"), dict) else {}
        subject = str(member.get("login") or member.get("id") or "")
    elif event_type == "gollum":
        pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
        subject = "|".join(sorted(str(page.get("sha") or page.get("page_name") or "") for page in pages))
    # star / public / repository 没有更细的对象，仓库本身已在去重键前缀里。
    return [actor, action, subject, _event_day(payload)]


def normalize_activity(repo: GithubRepository, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if event_type not in ACTIVITY_TYPES:
        return None
    # Only completed workflows; queued/in_progress would flood busy repositories.
    if event_type == "workflow_run" and payload.get("action") != "completed":
        return None
    actor = str((payload.get("sender") or {}).get("login") or (payload.get("pusher") or {}).get("name") or "GitHub")
    action = str(payload.get("action") or "")
    if event_type == "star" and action == "started":
        action = "created"
    if event_type == "fork":
        action = "forked"
    detail = ""
    url = repo.html_url
    identity: Any = None
    if event_type == "push":
        ref = str(payload.get("ref") or "")
        before = str(payload.get("before") or "")
        head = str(payload.get("after") or payload.get("head") or "")
        identity = [ref, before, head]
        commits = payload.get("commits") or []
        count = payload.get("size") or payload.get("distinct_size") or len(commits)
        branch = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        title = f"{actor} 向 {branch or '分支'} 推送代码" + (f"（{count} 个提交）" if count else "")
        detail = "\n".join(f"· {str(c.get('id') or c.get('sha') or '')[:7]} {str(c.get('message') or '').splitlines()[0] if c.get('message') else ''}" for c in commits[:8])
        if not detail:
            detail = f"提交：{head[:12]}" if head else "分支已更新"
        if payload.get("deleted"):
            title = f"{actor} 删除 {branch}"
        url = payload.get("compare") or (f"{repo.html_url}/commit/{head}" if head and set(head) != {"0"} else repo.html_url)
        # 卡片数据：webhook 的 commits 自带 added/modified/removed 文件清单；
        # 轮询路径由 sync_activity 用 compare 接口补的 _compare（含行数统计）。
        files: list[str] = []
        for commit in commits[:20]:
            for key in ("added", "modified", "removed"):
                files.extend(str(f) for f in (commit.get(key) or []) if f)
        compare = payload.get("_compare") if isinstance(payload.get("_compare"), dict) else None
        stats: dict[str, Any] | None = None
        if compare:
            compare_files = [str(f) for f in (compare.get("files") or []) if f]
            if compare_files:
                files = compare_files
            compare_stats = compare.get("stats") or {}
            if compare_stats:
                stats = {k: compare_stats.get(k) for k in ("additions", "deletions", "total")}
        card = {
            "kind": "push", "branch": branch, "author": actor, "head": head, "url": url,
            "repo_url": repo.html_url, "commits": [
                {"sha": str(c.get("id") or c.get("sha") or ""),
                 "message": str(c.get("message") or "").splitlines()[0] if c.get("message") else ""}
                for c in commits[:10]
            ],
            "commit_count": len(commits), "files": files[:20], "file_count": len(files), "stats": stats,
        }
    elif event_type in {"create", "delete"}:
        # 分支/标签的增删同样没有跨通道共用 ID，用 ref + 操作者 + 事件日期去重。
        identity = [payload.get("ref_type"), payload.get("ref"), actor, _event_day(payload)]
        title = f"{actor} {'创建' if event_type == 'create' else '删除'}{'标签' if payload.get('ref_type') == 'tag' else '分支'} {payload.get('ref') or ''}"
        card = {
            "kind": "activity", "event_type": event_type, "label": EVENT_LABELS[event_type],
            "title": title, "detail": "", "author": actor,
            "url": repo.html_url, "repo_url": repo.html_url,
        }
    else:
        entity = next((payload[k] for k in ("comment", "review", "workflow_run", "release", "pull_request", "issue", "discussion", "forkee", "member", "repository") if isinstance(payload.get(k), dict)), {})
        number = (payload.get("issue") or payload.get("pull_request") or payload.get("discussion") or {}).get("number") or payload.get("number")
        subject = entity.get("title") or entity.get("name") or entity.get("tag_name") or entity.get("full_name") or entity.get("login") or ""
        if event_type in {"star", "public"}:
            # Webhook 的 payload 带 repository 对象，轮询的 WatchEvent 不带；
            # 仓库名在正文「项目」一行已有，标题不再拼接，保证两条通道文案一致。
            subject = ""
        verb = "合并" if event_type == "pull_request" and (payload.get("pull_request") or {}).get("merged") and action == "closed" else ACTION_LABELS.get(action, action)
        title = f"{actor} {verb} {EVENT_LABELS[event_type]}" + (f" #{number}" if number else "") + (f"：{subject}" if subject else "")
        detail = strip_markdown(str(entity.get("body") or ""))
        if event_type == "workflow_run":
            detail = f"结果：{entity.get('conclusion') or entity.get('status')}\n分支：{entity.get('head_branch') or ''}"
        elif event_type == "gollum":
            detail = "\n".join(str(page.get("title") or "") for page in (payload.get("pages") or [])[:8])
        url = entity.get("html_url") or url
        identity = [entity.get("id") or number or actor, action, entity.get("updated_at"), subject, detail]
        card = {
            "kind": "activity", "event_type": event_type, "label": EVENT_LABELS[event_type],
            "title": title, "detail": truncate(detail, 600), "author": actor,
            "url": url, "repo_url": repo.html_url,
        }
    if event_type in CHANNEL_AGNOSTIC_TYPES:
        # 同一次 Star/Fork/成员变更不能因为「从哪条通道来」而被判成两条事件：
        # 丢掉通道私有 ID，只保留跨通道一致的语义字段。
        identity = _channel_agnostic_identity(event_type, actor, action, payload)
    key_data = json.dumps([event_type, identity], sort_keys=True, ensure_ascii=False)
    key = f"activity:{repo.id}:" + hashlib.sha256(key_data.encode()).hexdigest()
    return {"dedupe_key": key, "event_type": event_type, "action": action, "title": truncate(title, 250),
            "content": truncate(f"【GitHub · {EVENT_LABELS[event_type]}】\n项目：{repo.full_name}\n{title}\n{truncate(detail, 1000)}\n{url}", 1800),
            "card": card}


async def ingest_activity(db: AsyncSession, repo: GithubRepository, event_type: str, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    data = normalize_activity(repo, event_type, payload)
    if not data:
        return {"ok": True, "new_events": 0, "pushed": 0}
    event = await db.scalar(select(GithubEvent).where(GithubEvent.dedupe_key == data["dedupe_key"]))
    is_new = event is None
    if event is None:
        event = GithubEvent(repository_id=repo.id, event_type=event_type, action=data["action"], dedupe_key=data["dedupe_key"], source=source,
                            payload={"title": data["title"], "content": data["content"], "card": data.get("card")})
        db.add(event)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            event = await db.scalar(select(GithubEvent).where(GithubEvent.dedupe_key == data["dedupe_key"]))
    assert event is not None
    records = await dispatch_activity(db, repo, event)
    event.processed = True
    if source == "webhook":
        repo.last_webhook_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "new_events": int(is_new), "pushed": sum(r.status == "success" for r in records)}


async def dispatch_activity(db: AsyncSession, repo: GithubRepository, event: GithubEvent) -> list[PushRecord]:
    from app.services.account_manager import account_manager
    from app.services.github.access import scoped_push_query

    if repo.archived_at is not None:
        return []
    rule_rows = list(await db.scalars(scoped_push_query(repo.id)))
    # 判据快照成普通元组：并发回滚会让会话内所有 ORM 实例过期，之后再读
    # rule.event_types 会触发异步上下文里的懒加载并抛出 MissingGreenlet（接口 500）。
    snapshot = [(row.id, tuple(row.event_types or ["release"])) for row in rule_rows]
    records = []
    for rule_id, event_types in snapshot:
        if event.event_type not in event_types:
            continue
        rule = await db.get(PushRule, rule_id, populate_existing=True)
        if rule is None:
            continue
        if await db.scalar(select(PushRecord.id).where(PushRecord.rule_id == rule_id, PushRecord.event_id == event.id)):
            continue
        record = PushRecord(repository_id=repo.id, rule_id=rule_id, event_id=event.id, account_id=rule.account_id, qq_group=rule.qq_group,
                            release_tag=str(event.payload.get("title") or event.event_type)[:128], content=event.payload.get("content") or "", status="pending")
        db.add(record)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            # 回滚后 repo / event 也会过期，下一轮读取前显式重新加载。
            with contextlib.suppress(Exception):
                await db.refresh(repo)
                await db.refresh(event)
            continue
        try:
            if not account_manager.is_online(rule.account_id):
                raise RuntimeError("账号不在线，等待重试")
            result = await send_push_record(db, record, rule, repo)
            record.message_id = (result.get("data") or {}).get("message_id")
            record.status = "success"
            record.sent_at = datetime.now(timezone.utc)
            rule.total_pushed += 1
            rule.last_pushed_at = record.sent_at
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            record.error = str(exc)[:500]
        await db.commit()
        if record.status == "failed":
            from app.services.logs import write_log
            await write_log(db, level="ERROR", category="push", account_id=rule.account_id,
                            message=f"仓库 {repo.full_name} 动态投递失败：{record.error}")
        records.append(record)
    return records


def _parse_event_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def sync_activity(db: AsyncSession, repo: GithubRepository, client, *, notify: bool) -> dict[str, Any]:
    rows: list[dict] = []
    found = False
    cursor = repo.activity_cursor
    initialized = repo.activity_initialized_at is not None
    for page in range(1, 4):
        batch = await client.list_events(repo.owner, repo.name, page=page)
        for item in batch:
            if str(item.get("id")) == cursor:
                found = True
                break
            rows.append(item)
        if found or len(batch) < 100 or not initialized:
            break
    warning = None
    if initialized and cursor and not found and len(rows) >= 300:
        warning = "动态超过 GitHub 最近 300 条上限，可能存在缺口；请启用实时 Webhook"
    stats: dict[str, Any] = {"new_events": 0, "pushed": 0, "warning": warning}
    # GitHub 事件流偶尔会迟到补发旧事件（比如升级重启后重新轮询），
    # 超过 24 小时的动态直接丢弃，避免在群里迟到播报几天前的推送。
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stale_skipped = 0
    for item in reversed(rows) if initialized and notify else []:
        event_type = POLL_TYPES.get(item.get("type"))
        if not event_type:
            continue
        created_at = _parse_event_time(item.get("created_at"))
        if created_at is not None and created_at < stale_cutoff:
            stale_skipped += 1
            continue
        payload = dict(item.get("payload") or {})
        payload["sender"] = item.get("actor") or {}
        payload["_event_id"] = str(item.get("id") or "")
        # 事件真实发生时间：去重键需要它，才能在轮询迟到数小时后仍与 Webhook 判为同一条。
        payload["_occurred_at"] = item.get("created_at")
        if event_type == "push" and not payload.get("commits"):
            before, head = payload.get("before"), payload.get("head")
            if before and head and set(before) != {"0"}:
                try:
                    compared = await client.compare_commits(repo.owner, repo.name, before, head)
                    payload["commits"] = [{"id": c.get("sha"), "message": (c.get("commit") or {}).get("message")} for c in compared.get("commits", [])[:8]]
                    # compare 响应顺便带出行数统计与文件清单，供 Markdown 卡片的「统计信息」段使用。
                    payload["_compare"] = {
                        "stats": compared.get("stats") or {},
                        "files": [str(f.get("filename") or "") for f in (compared.get("files") or []) if f.get("filename")],
                    }
                except Exception as exc:  # noqa: BLE001
                    # A force-push can remove the comparison base; still report the push.
                    if getattr(exc, "rate_limited", False):
                        raise
        result = await ingest_activity(db, repo, event_type, payload, source="poll")
        stats["new_events"] += result["new_events"]
        stats["pushed"] += result["pushed"]
    if stale_skipped:
        from app.services.logs import write_log

        await write_log(
            db,
            level="INFO",
            category="github",
            message=f"{repo.full_name} 跳过 {stale_skipped} 条超过 24 小时的陈旧动态，避免迟到播报",
        )
    if rows:
        repo.activity_cursor = str(rows[0]["id"])
    repo.activity_initialized_at = repo.activity_initialized_at or datetime.now(timezone.utc)
    repo.poll_interval_seconds = max(repo.poll_interval_seconds, client.poll_interval)
    await db.commit()
    return stats
