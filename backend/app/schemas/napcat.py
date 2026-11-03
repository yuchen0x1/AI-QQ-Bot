"""NapCat 扫码登录接口 DTO。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NapCatInstanceOut(BaseModel):
    id: str
    name: str


class NapCatLoginStart(BaseModel):
    instance_id: str | None = None
    name: str | None = Field(default=None, max_length=96)


class NapCatLoginOut(BaseModel):
    session_id: str
    instance_id: str
    instance_name: str
    qrcode: str
    status: Literal["waiting_qrcode", "qrcode_scanned", "initializing", "online", "offline", "error"]
    expires_at: int
    message: str | None = None


class NapCatLoginStatusOut(BaseModel):
    session_id: str
    instance_id: str
    instance_name: str
    status: Literal["waiting_qrcode", "qrcode_scanned", "initializing", "online", "offline", "error"]
    qrcode: str | None = None
    login_phase: str | None = None
    login_error: str | None = None
    qq_number: int | None = None
    nickname: str | None = None
    expires_at: int
    message: str | None = None
    account: dict[str, Any] | None = None
