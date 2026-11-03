"""通用 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


class MessageOut(BaseModel):
    detail: str
    ok: bool = True


class IdOut(BaseModel):
    id: int


class TimeRange(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class ActionResult(BaseModel):
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class TestResult(BaseModel):
    ok: bool
    latency_ms: int | None = None
    message: str
    detail: dict[str, Any] | None = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
