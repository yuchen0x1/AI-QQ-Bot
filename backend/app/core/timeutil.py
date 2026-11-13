"""业务时区的日界线计算。

数据库统一存 UTC，但"今日消息""最近 7 天趋势"这类展示口径必须按运营者所在时区
切分。此前直接用 ``datetime.now(timezone.utc).replace(hour=0, ...)``，在 UTC+8 下
会让每天的时间窗整体偏移 8 小时（凌晨 0-8 点的数据被算进前一天），仪表盘与消息
统计因此系统性失真。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import settings

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ 内置
    ZoneInfo = None  # type: ignore[assignment]


def business_timezone() -> timezone | ZoneInfo:
    """运营时区，取自 SCHEDULER_TIMEZONE（默认 Asia/Shanghai）。"""
    name = (settings.scheduler_timezone or "UTC").strip()
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - 无效时区名回退 UTC
            pass
    return timezone.utc


def day_start(days_ago: int = 0) -> datetime:
    """返回 N 天前当天 00:00 的 UTC 时间点，按业务时区切分。"""
    now = datetime.now(business_timezone())
    local_midnight = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def local_day_key(value: datetime) -> str:
    """把 UTC 时间转成业务时区的 YYYY-MM-DD，用于按天分组。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(business_timezone()).date().isoformat()


def local_day(days_ago: int = 0) -> str:
    """业务时区下 N 天前的日期字符串（YYYY-MM-DD）。"""
    return (datetime.now(business_timezone()) - timedelta(days=days_ago)).date().isoformat()


def date_bucket(column, dialect: str):
    """返回"按业务时区切日"的 SQL 表达式，用于 GROUP BY 日期。

    ``func.date(utc_column)`` 直接分组等于按 UTC 切天，UTC+8 下会把 0-8 点的
    数据算到前一天。这里按方言换算到业务时区：
      * PostgreSQL: ``date(timezone('Asia/Shanghai', ts))``
      * SQLite（测试）: ``strftime('%Y-%m-%d', datetime(ts, '+480 minutes'))``
    """
    from sqlalchemy import func

    if dialect == "postgresql":
        return func.date(func.timezone(_timezone_name(), column))
    if dialect == "sqlite":
        offset = datetime.now(business_timezone()).utcoffset() or timedelta(0)
        minutes = int(offset.total_seconds() // 60)
        sign = "+" if minutes >= 0 else "-"
        return func.strftime("%Y-%m-%d", func.datetime(column, f"{sign}{abs(minutes)} minutes"))
    return func.date(column)


def _timezone_name() -> str:
    return (settings.scheduler_timezone or "UTC").strip()


__all__ = ["business_timezone", "date_bucket", "day_start", "local_day", "local_day_key"]
