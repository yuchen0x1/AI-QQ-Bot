"""`system_settings` 取值的统一入口。

该表的历史数据存在两种形态：``{"value": 30}``（种子与更新接口写入）和裸值 ``30``
（早期版本或人工改库）。各处此前各自写 ``(row.value or {}).get("value")``，
一旦遇到裸值就抛 ``AttributeError: 'int' object has no attribute 'get'``，
而这类异常发生在定时任务里会静默失败。统一走这里做兼容。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemSetting


def setting_value(row: SystemSetting | None, default: Any = None) -> Any:
    """从 SystemSetting 行里取出真实值，兼容 dict 包装与裸值。"""
    if row is None:
        return default
    raw = row.value
    if isinstance(raw, dict):
        return raw.get("value", default)
    return raw if raw is not None else default


async def read_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    return setting_value(row, default)


__all__ = ["read_setting", "setting_value"]
