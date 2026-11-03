"""群自动管理：关键词、广告、刷屏、频率限制、黑白名单，所有处罚均需权限校验并留审计。"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GroupMember, GroupSettings, Message

AD_PATTERNS = [
    re.compile(r"(https?://|www\.)\S+", re.I),
    re.compile(r"(加群|扫码|私聊我|代刷|兼职|日赚|低价|出售|免费领)"),
    re.compile(r"[1-9]\d{4,10}"),  # 疑似 QQ 号/群号
]


@dataclass
class ModerationVerdict:
    action: str = "none"  # none/warn/mute/kick
    reason: str = ""
    duration: int = 0
    blocked: bool = False


class RateTracker:
    """进程内滑动窗口频率统计（按 账号:群:用户）。"""

    def __init__(self, window: int = 60) -> None:
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._recent: dict[str, deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=10))

    def hit(self, key: str, content: str) -> tuple[int, int]:
        now = time.monotonic()
        bucket = self._hits[key]
        bucket.append(now)
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        recent = self._recent[key]
        recent.append((now, content))
        repeat = 0
        for ts, text in reversed(recent):
            if now - ts > 120:
                break
            if text == content:
                repeat += 1
            else:
                break
        return len(bucket), repeat

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
        self._recent.pop(key, None)


rate_tracker = RateTracker()


class ModerationService:
    async def evaluate(
        self,
        db: AsyncSession,
        *,
        account_id: int,
        group_number: int,
        user_id: int,
        content: str,
        settings: GroupSettings,
        member: GroupMember | None,
        sender_role: str,
    ) -> ModerationVerdict:
        if sender_role in {"owner", "admin"}:
            return ModerationVerdict()
        if member and member.is_whitelisted:
            return ModerationVerdict()
        mode = settings.moderation_mode or "normal"
        if mode == "off":
            return ModerationVerdict()

        strict = mode == "strict"

        # 1. 黑名单
        if member and member.is_blacklisted:
            return ModerationVerdict(action="kick" if strict else "mute", reason="命中群黑名单", duration=3600, blocked=True)

        # 2. 违禁词
        text = (content or "").strip()
        lowered = text.lower()
        for word in settings.banned_words or []:
            if word and word.lower() in lowered:
                return self._penalty(member, f"命中违禁词「{word}」", settings, strict)

        # 3. 刷屏 / 重复
        key = f"{account_id}:{group_number}:{user_id}"
        count, repeat = rate_tracker.hit(key, text)
        threshold = max(1, settings.max_repeat_chars)
        if strict and repeat >= max(2, threshold):
            return self._penalty(member, f"重复发送相同内容 {repeat} 次", settings, strict)
        if not strict and repeat >= max(3, threshold + 2):
            return self._penalty(member, f"重复发送相同内容 {repeat} 次", settings, strict)

        # 4. 频率
        limit = settings.rate_limit_per_minute
        if limit and count > limit:
            return self._penalty(member, f"消息频率超限（{count}/{limit} 每分钟）", settings, strict)

        # 5. 广告（严格模式）
        if strict:
            for pattern in AD_PATTERNS:
                if pattern.search(text):
                    return self._penalty(member, "疑似广告或引流内容", settings, strict)
        return ModerationVerdict()

    def _penalty(
        self, member: GroupMember | None, reason: str, settings: GroupSettings, strict: bool
    ) -> ModerationVerdict:
        warns = (member.warn_count if member else 0) + 1
        threshold = max(1, settings.auto_warn_threshold)
        if settings.auto_kick and warns >= threshold * 2:
            return ModerationVerdict(action="kick", reason=f"{reason}；累计警告 {warns} 次", blocked=True)
        if warns >= threshold:
            return ModerationVerdict(
                action="mute",
                reason=f"{reason}；累计警告 {warns} 次",
                duration=max(60, settings.auto_mute_seconds),
                blocked=True,
            )
        return ModerationVerdict(action="warn", reason=f"{reason}；警告 {warns}/{threshold}", blocked=False)


moderation = ModerationService()


async def record_warning(db: AsyncSession, member: GroupMember | None) -> None:
    if member is None:
        return
    member.warn_count += 1
    await db.commit()


async def reset_warnings(db: AsyncSession, group_id: int, user_id: int) -> None:
    member = await db.scalar(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))
    if member:
        member.warn_count = 0
        await db.commit()


async def recent_message_count(db: AsyncSession, account_id: int, group_number: int, since: datetime) -> int:
    rows = await db.scalars(
        select(Message.id).where(
            Message.account_id == account_id,
            Message.qq_group == group_number,
            Message.created_at >= since,
        )
    )
    return len(list(rows))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
