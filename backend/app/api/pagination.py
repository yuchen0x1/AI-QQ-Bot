"""分页查询参数的统一约束。

历史实现里各端点直写 ``page_size: int = 20``，没有任何上界，调用方可以传
``page_size=1000000`` 让单次查询拉全表。这里集中定义带边界的 Annotated 类型，
新端点直接复用即可。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

PageParam = Annotated[int, Query(ge=1, description="页码，从 1 开始")]
PageSizeParam = Annotated[int, Query(ge=1, le=200, description="每页条数，最大 200")]

__all__ = ["PageParam", "PageSizeParam"]
