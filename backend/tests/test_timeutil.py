"""业务时区日界线测试。

此前仪表盘/消息统计直接用 UTC 零点切天，UTC+8 运营时区下每天 0-8 点的数据
会被算进前一天。这里锁定修复后的行为。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core import timeutil
from app.core.config import settings


@pytest.fixture()
def shanghai(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "Asia/Shanghai", raising=False)
    return timezone(timedelta(hours=8))


def test_day_start_is_local_midnight(shanghai):
    start = timeutil.day_start()
    local = start.astimezone(shanghai)
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)
    assert start.tzinfo is not None


def test_day_start_offset_moves_whole_days(shanghai):
    today = timeutil.day_start()
    yesterday = timeutil.day_start(1)
    assert today - yesterday == timedelta(days=1)


def test_local_day_key_uses_business_timezone(shanghai):
    # UTC 2026-01-01 20:00 == 上海 2026-01-02 04:00
    utc_value = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
    assert timeutil.local_day_key(utc_value) == "2026-01-02"


def test_local_day_key_treats_naive_as_utc(shanghai):
    naive = datetime(2026, 1, 1, 20, 0)
    assert timeutil.local_day_key(naive) == "2026-01-02"


def test_local_day_matches_day_start(shanghai):
    assert timeutil.local_day() == timeutil.day_start().astimezone(shanghai).date().isoformat()
    assert timeutil.local_day(3) == timeutil.day_start(3).astimezone(shanghai).date().isoformat()


def test_invalid_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "Not/AZone", raising=False)
    assert timeutil.business_timezone() is timezone.utc


def test_date_bucket_sqlite_shifts_by_offset(monkeypatch):
    """SQLite 分支按分钟偏移换算，验证生成的 SQL 片段。"""
    monkeypatch.setattr(settings, "scheduler_timezone", "Asia/Shanghai", raising=False)
    from sqlalchemy import Column, DateTime, MetaData, Table

    table = Table("t", MetaData(), Column("created_at", DateTime(timezone=True)))
    expr = timeutil.date_bucket(table.c.created_at, "sqlite")
    compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
    assert "strftime" in compiled
    assert "+480 minutes" in compiled


def test_date_bucket_postgresql_uses_timezone(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_timezone", "Asia/Shanghai", raising=False)
    from sqlalchemy import Column, DateTime, MetaData, Table
    from sqlalchemy.dialects import postgresql

    table = Table("t", MetaData(), Column("created_at", DateTime(timezone=True)))
    expr = timeutil.date_bucket(table.c.created_at, "postgresql")
    compiled = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "timezone" in compiled.lower()
    assert "Asia/Shanghai" in compiled
