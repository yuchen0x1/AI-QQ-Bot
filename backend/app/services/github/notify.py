"""Release 通知渲染、QQ 群推送、去重与失败重试。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models import Account, GithubRelease, GithubRepository, PushRecord, PushRule
from app.services.ai import service as ai_service
from app.services.logs import write_log
from app.services.templates import render_template, strip_markdown, truncate

logger = logging.getLogger("qbot.github.push")

DEFAULT_TEMPLATE = """【GitHub 项目更新通知】

项目：{repo_name}
版本：{version}
更新时间：{published_at}

更新内容：
{changelog}

更新日志：
{release_url}

下载地址：
{downloads}

机器人自动监控通知，请关注项目更新。"""

AI_SUMMARY_PROMPT = """你是开源项目的发布说明编辑。请阅读下面的 GitHub Release 内容，输出面向中文 QQ 群读者的简洁更新摘要。
要求：
1. 用「新增 / 优化 / 修复 / 重要变化」四类分条列出，每条不超过 30 字；
2. 只保留对用户有实际价值的信息，忽略签名、贡献者列表等噪音；
3. 不要输出 Markdown 标题，不要输出多余寒暄，总长度不超过 400 字；
4. 如果原文信息极少，就如实概括，不要编造。"""


def format_assets(assets: list[dict[str, Any]]) -> str:
    if not assets:
        return "暂无附件"
    lines: list[str] = []
    for asset in assets[:8]:
        name = asset.get("name") or "未命名文件"
        size = asset.get("size") or 0
        size_mb = f"{size / 1024 / 1024:.1f} MB" if size else "未知大小"
        url = asset.get("browser_download_url") or ""
        lines.append(f"· {name}（{size_mb}）\n  {url}")
    if len(assets) > 8:
        lines.append(f"…… 另有 {len(assets) - 8} 个文件，请前往 Release 页面查看")
    return "\n".join(lines)


def build_values(repo: GithubRepository, release: GithubRelease, *, changelog: str, summary: str = "") -> dict[str, Any]:
    published = release.published_at.strftime("%Y-%m-%d %H:%M") if release.published_at else "未知"
    return {
        "repo_name": repo.name,
        "full_name": repo.full_name,
        "owner": repo.owner,
        "description": repo.description or "",
        "version": release.tag_name,
        "release_title": release.name or release.tag_name,
        "published_at": published,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "changelog": changelog,
        "raw_changelog": strip_markdown(release.body or "")[:1200],
        "ai_summary": summary,
        "release_url": release.html_url or repo.html_url,
        "repo_url": repo.html_url,
        "downloads": format_assets(release.assets or []),
        "prerelease": "是" if release.prerelease else "否",
    }


async def generate_summary(db: AsyncSession, repo: GithubRepository, release: GithubRelease) -> str:
    """调用 AI 生成中文更新摘要；失败时返回空字符串，由调用方回退到原始日志。"""
    if release.summary:
        return release.summary
    model = await ai_service.resolve_model(db)
    if not model:
        release.summary_status = "no_model"
        await db.commit()
        return ""
    content = strip_markdown(release.body or "")
    if not content:
        release.summary_status = "empty_body"
        await db.commit()
        return ""
    prompt = f"项目：{repo.full_name}\n版本：{release.tag_name}\n发布时间：{release.published_at}\n\n原始更新日志：\n{content[:6000]}"
    result, error, _ = await ai_service.chat_once(
        db,
        model,
        [{"role": "user", "content": prompt}],
        system=AI_SUMMARY_PROMPT,
        allow_fallback=True,
    )
    if not result or not result.content.strip():
        release.summary_status = "failed"
        await db.commit()
        await write_log(
            db,
            level="WARNING",
            category="github",
            message=f"AI 更新摘要生成失败，使用原始日志：{error}",
            context={"repo": repo.full_name, "tag": release.tag_name},
        )
        return ""
    release.summary = result.content.strip()
    release.summary_status = "ok"
    await db.commit()
    return release.summary


async def build_message(
    db: AsyncSession, repo: GithubRepository, release: GithubRelease, rule: PushRule
) -> str:
    summary = ""
    if rule.ai_summary:
        summary = await generate_summary(db, repo, release)
    changelog = summary or strip_markdown(release.body or "") or "本次发布未提供更新日志。"
    if rule.include_changelog is False:
        changelog = "（已关闭更新日志推送）"
    if not rule.include_downloads:
        values_assets = "（已关闭下载地址推送）"
    else:
        values_assets = None
    template = rule.template or DEFAULT_TEMPLATE
    values = build_values(repo, release, changelog=truncate(changelog, 1000), summary=summary)
    if values_assets is not None:
        values["downloads"] = values_assets
    message = render_template(template, values)
    if rule.mention_user_ids:
        mentions = " ".join(f"[CQ:at,qq={uid}]" for uid in rule.mention_user_ids if uid)
        message = f"{mentions}\n{message}"
    return truncate(message, 1800)


async def dispatch_release(
    db: AsyncSession,
    repo: GithubRepository,
    release: GithubRelease,
    *,
    source: str = "poll",
) -> list[PushRecord]:
    """按推送规则发送通知；同一规则 + 同一 Release 只会成功入库一次。"""
    from app.services.account_manager import account_manager

    rules = list(await db.scalars(select(PushRule).where(PushRule.repository_id == repo.id, PushRule.enabled.is_(True))))
    records: list[PushRecord] = []
    for rule in rules:
        if rule.only_stable and release.prerelease:
            continue
        existing = await db.scalar(
            select(PushRecord).where(PushRecord.rule_id == rule.id, PushRecord.release_id == release.id)
        )
        if existing:
            continue
        content = ""
        try:
            content = await build_message(db, repo, release, rule)
        except Exception as exc:  # noqa: BLE001
            logger.exception("渲染推送消息失败")
            content = f"【GitHub 项目更新通知】\n项目：{repo.full_name}\n版本：{release.tag_name}\n{release.html_url or ''}\n（消息渲染异常：{exc}）"

        record = PushRecord(
            repository_id=repo.id,
            rule_id=rule.id,
            release_id=release.id,
            release_tag=release.tag_name,
            account_id=rule.account_id,
            qq_group=rule.qq_group,
            content=content,
            status="pending",
        )
        db.add(record)
        try:
            await db.commit()
        except Exception:  # 并发下唯一约束冲突
            await db.rollback()
            continue

        account = await db.get(Account, rule.account_id)
        if not account:
            record.status = "failed"
            record.error = "推送规则绑定的 QQ 账号不存在"
            await db.commit()
            records.append(record)
            continue

        try:
            # Resolve the intended account's live runtime before dispatch. Never fall back to
            # another active adapter: cross-account delivery is a data-isolation violation.
            if not account_manager.is_online(rule.account_id):
                raise RuntimeError("账号不在线，无法发送消息")
            result = await account_manager.send_group_message(rule.account_id, rule.qq_group, content)
            data = result.get("data") or {}
            record.status = "success"
            record.message_id = data.get("message_id")
            record.sent_at = datetime.now(timezone.utc)
            rule.total_pushed += 1
            rule.last_pushed_at = record.sent_at
            release.notified = True
            await db.commit()
            await write_log(
                db,
                level="INFO",
                category="push",
                message=f"已推送 {repo.full_name} {release.tag_name} 到群 {rule.qq_group}",
                account_id=rule.account_id,
                context={"repo": repo.full_name, "tag": release.tag_name, "source": source},
            )
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            record.error = str(exc)[:500]
            await db.commit()
            await write_log(
                db,
                level="ERROR",
                category="push",
                message=f"推送失败 {repo.full_name} {release.tag_name} -> 群 {rule.qq_group}：{exc}",
                account_id=rule.account_id,
            )
        records.append(record)
    return records


async def retry_failed_pushes(db: AsyncSession, limit: int = 20) -> dict[str, int]:
    from app.services.account_manager import account_manager

    rows = await db.scalars(
        select(PushRecord)
        .where(PushRecord.status == "failed", PushRecord.retries < app_settings.push_max_retries)
        .order_by(PushRecord.id.asc())
        .limit(limit)
    )
    stats = {"attempted": 0, "success": 0, "failed": 0}
    for record in list(rows):
        stats["attempted"] += 1
        record.retries += 1
        try:
            result = await account_manager.send_group_message(record.account_id, record.qq_group, record.content or "")
            data = result.get("data") or {}
            record.status = "success"
            record.message_id = data.get("message_id")
            record.sent_at = datetime.now(timezone.utc)
            record.error = None
            stats["success"] += 1
        except Exception as exc:  # noqa: BLE001
            record.error = str(exc)[:500]
            stats["failed"] += 1
        await db.commit()
    return stats


async def resend_record(db: AsyncSession, record: PushRecord) -> PushRecord:
    """手动重新推送（不受去重限制，但会记录重试次数）。"""
    from app.services.account_manager import account_manager

    record.retries += 1
    try:
        result = await account_manager.send_group_message(record.account_id, record.qq_group, record.content or "")
        data = result.get("data") or {}
        record.status = "success"
        record.message_id = data.get("message_id")
        record.sent_at = datetime.now(timezone.utc)
        record.error = None
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = str(exc)[:500]
    await db.commit()
    await db.refresh(record)
    return record
