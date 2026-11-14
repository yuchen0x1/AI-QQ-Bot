"""QQ 官方 Markdown 卡片渲染与投递。

官方机器人 msg_type=2 原生 Markdown + keyboard 底部按钮，渲染出的深色卡片即
群里常见的「GitHub 推送卡片」。原生 Markdown 与自定义按钮都需要机器人在开放
平台拥有对应权限；未开通时接口直接报错，因此发送层一律先试卡片、失败自动降级
纯文本，保证推送永不中断。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.timeutil import business_timezone
from app.models import GithubEvent, GithubRepository, PushRecord, PushRule
from app.services.logs import write_log

logger = logging.getLogger("qbot.github.card")

# 官方 keyboard 约束：最多 5 行、每行最多 5 个按钮。
MAX_ROWS = 5
MAX_BUTTONS_PER_ROW = 5
MAX_COMMIT_LINES = 10
MAX_FILES = 20
MAX_DETAIL_CHARS = 600

EVENT_EMOJI = {
    "push": "🎉", "release": "🚀", "issues": "🐛", "pull_request": "🔀",
    "issue_comment": "💬", "pull_request_review": "👀", "pull_request_review_comment": "💬",
    "create": "🌱", "delete": "🗑️", "star": "⭐", "fork": "🍴",
    "workflow_run": "🤖", "discussion": "🗣️", "discussion_comment": "🗣️",
    "public": "📢", "repository": "📦", "gollum": "📖", "member": "👥",
}
UNSUPPORT_TIPS = "当前 QQ 版本不支持跳转链接"

_FENCE_RUN = re.compile(r"```+")


def _code_block(text: str, *, limit: int = 900) -> str:
    """把任意内容包进围栏代码块；中和内容里的三连反引号，防止提前闭合围栏。"""
    text = _FENCE_RUN.sub("``", str(text or "")).strip("\n") or "（无内容）"
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n……"
    return f"```\n{text}\n```"


def _link_button(button_id: str, label: str, url: str, *, style: int = 1) -> dict[str, Any]:
    """跳转按钮：type=0 http、permission type=2 所有人可点、style 1 蓝色线框。"""
    return {
        "id": button_id,
        "render_data": {"label": label, "visited_label": label, "style": style},
        "action": {
            "type": 0,
            "permission": {"type": 2},
            "data": url,
            "unsupport_tips": UNSUPPORT_TIPS,
        },
    }


def _keyboard(rows: list[list[dict[str, Any]]]) -> dict[str, Any] | None:
    filled = [{"buttons": row[:MAX_BUTTONS_PER_ROW]} for row in rows if row]
    return {"content": {"rows": filled[:MAX_ROWS]}} if filled else None


def _local_time(value: datetime | None) -> str:
    if value is None:
        return "未知"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(business_timezone()).strftime("%Y/%m/%d %H:%M:%S")


def _push_markdown(card: dict[str, Any], event: GithubEvent) -> str:
    emoji = EVENT_EMOJI["push"]
    branch = card.get("branch") or "未知分支"
    commits = card.get("commits") or []
    lines: list[str] = [
        f"## {emoji} 检测到新的代码推送",
        "",
        f"**{card.get('repo_name') or ''}**",
        f"分支：{branch}",
        "",
        "---",
        "",
        "### 提交内容",
        "",
    ]
    if commits:
        lines.append(_code_block(
            "\n".join(
                f"{str(c.get('sha') or '')[:7]} {str(c.get('message') or '').strip() or '（无提交说明）'}"
                for c in commits[:MAX_COMMIT_LINES]
            ),
            limit=900,
        ))
    else:
        lines.append(_code_block("（推送未携带提交明细）"))
    files = card.get("files") or []
    file_count = card.get("file_count")
    if file_count is None:
        file_count = len(files)
    if files:
        lines += ["", "### 变化文件", "", _code_block("\n".join(files), limit=900)]
    stats = card.get("stats") or {}
    stat_lines = [f"提交数量：{card.get('commit_count') if card.get('commit_count') is not None else len(commits)}"]
    if file_count:
        stat_lines.append(f"变化文件：{file_count}")
    if stats.get("additions") is not None:
        stat_lines += [
            f"新增行数：{stats.get('additions')}",
            f"减少行数：{stats.get('deletions')}",
            f"变化行数：{stats.get('total') if stats.get('total') is not None else stats.get('additions', 0) + stats.get('deletions', 0)}",
        ]
    lines += ["", "### 统计信息", "", *stat_lines]
    author = card.get("author") or "未知"
    head = str(card.get("head") or "")
    lines += [
        "",
        "### 提交信息",
        "",
        f"提交者：{author}",
        f"提交时间：{_local_time(event.created_at)}",
    ]
    if head:
        lines += ["Commit SHA：", f"`{head}`"]
    return "\n".join(lines)


def _activity_markdown(card: dict[str, Any]) -> str:
    label = card.get("label") or "仓库动态"
    emoji = EVENT_EMOJI.get(str(card.get("event_type") or ""), "🔔")
    lines = [
        f"## {emoji} {label}",
        "",
        f"**{card.get('repo_name') or ''}**",
        "",
        str(card.get("title") or "").strip() or "仓库有新的动态",
        "",
        "---",
        "",
        "### 动态详情",
        "",
    ]
    detail = str(card.get("detail") or "").strip()
    if detail:
        lines.append(_code_block(detail, limit=MAX_DETAIL_CHARS + 100))
    else:
        lines.append("（无正文内容）")
    author = card.get("author")
    if author:
        lines += ["", f"操作者：{author}"]
    return "\n".join(lines)


def build_event_card(repo: GithubRepository, event: GithubEvent | None) -> dict[str, Any] | None:
    """从事件 payload 的 card 数据渲染 {markdown, keyboard}；没有卡片数据返回 None。"""
    if event is None:
        return None
    payload = event.payload or {}
    card = payload.get("card")
    if not isinstance(card, dict):
        return None
    card = {**card, "repo_name": repo.full_name}
    if card.get("kind") == "push":
        markdown = _push_markdown(card, event)
        url = str(card.get("url") or "")
        link_label = "查看变更"
    else:
        card.setdefault("event_type", event.event_type)
        markdown = _activity_markdown(card)
        url = str(card.get("url") or "")
        link_label = "查看详情"
    repo_url = str(repo.html_url or "")
    row: list[dict[str, Any]] = []
    if repo_url:
        row.append(_link_button("repo_home", "仓库主页", repo_url))
    if url and url != repo_url:
        row.append(_link_button("event_link", link_label, url))
    keyboard = _keyboard([row]) if row else None
    return {"markdown": {"content": markdown}, "keyboard": keyboard}


def _release_markdown(card: dict[str, Any]) -> str:
    version = card.get("version") or "未知版本"
    suffix = "（预发布）" if card.get("prerelease") else ""
    changelog = str(card.get("changelog") or "").strip()
    lines = [
        f"## 🚀 发布新版本 {version}{suffix}",
        "",
        f"**{card.get('repo_name') or ''}**",
        f"发布时间：{card.get('published_at') or '未知'}",
        "",
        "---",
        "",
        "### 更新内容",
        "",
    ]
    if changelog:
        lines.append(_code_block(changelog, limit=1100))
    else:
        # 规则关闭了更新日志：明说，而不是谎称"未提供"
        lines.append("（已关闭更新日志推送）")
    downloads = str(card.get("downloads") or "").strip()
    if downloads:
        lines += ["", "### 下载与发布资产", "", _code_block(downloads, limit=500)]
    return "\n".join(lines)


def build_release_card(repo: GithubRepository, card_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """从推送记录存储的 release 卡片数据渲染 {markdown, keyboard}；数据无效返回 None。"""
    if not isinstance(card_data, dict) or card_data.get("kind") != "release":
        return None
    card = {**card_data, "repo_name": repo.full_name}
    markdown = _release_markdown(card)
    repo_url = str(repo.html_url or "")
    url = str(card.get("url") or "")
    row: list[dict[str, Any]] = []
    if repo_url:
        row.append(_link_button("repo_home", "仓库主页", repo_url))
    if url and url != repo_url:
        row.append(_link_button("release_page", "发布页", url))
    keyboard = _keyboard([row]) if row else None
    return {"markdown": {"content": markdown}, "keyboard": keyboard}


async def send_push_record(db, record: PushRecord, rule: PushRule, repo: GithubRepository) -> dict[str, Any]:
    """按规则投递一条推送记录：开启 markdown_card 且有卡片数据时优先卡片，失败自动降级纯文本。

    卡片来源两种：版本发布记录自带 card_payload（随记录持久化，重试/重发仍能发卡片）；
    动态事件按 event_id 取 GithubEvent 现场渲染。卡片渲染失败 / 机器人没有 Markdown
    权限 / 客户端限制都只影响本次外观，绝不影响推送送达——这是推送链路的硬性要求。
    """
    from app.services.account_manager import account_manager

    content = record.content or ""
    card: dict[str, Any] | None = None
    if rule.markdown_card:
        stored = record.card_payload
        if isinstance(stored, dict):
            try:
                card = build_release_card(repo, stored)
            except Exception:  # noqa: BLE001 - 卡片渲染失败绝不阻断推送
                logger.exception("渲染 Markdown 卡片失败，将使用纯文本")
        elif record.event_id:
            event = await db.get(GithubEvent, record.event_id)
            if event is not None:
                try:
                    card = build_event_card(repo, event)
                except Exception:  # noqa: BLE001
                    logger.exception("渲染 Markdown 卡片失败，将使用纯文本")
    if card is not None:
        try:
            return await account_manager.send_group_message(
                record.account_id, record.qq_group, content,
                markdown=card["markdown"], keyboard=card.get("keyboard"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Markdown 卡片发送失败，降级为纯文本：%s", exc)
            try:
                await write_log(
                    db, level="WARNING", category="push", account_id=record.account_id,
                    message=f"Markdown 卡片发送失败，已降级为纯文本：{exc}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("写入卡片降级日志失败")
    return await account_manager.send_group_message(record.account_id, record.qq_group, content)
