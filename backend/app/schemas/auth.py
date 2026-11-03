"""认证与用户 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class RoleOut(ORMModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[str] = []


class UserOut(ORMModel):
    id: int
    username: str
    email: str | None = None
    display_name: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    role: RoleOut | None = None

    @computed_field
    @property
    def permissions(self) -> list[str]:
        if self.role and self.role.name == "super_admin":
            return ["*"]
        return list(self.role.permissions or []) if self.role else []


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = None
    display_name: str | None = None
    role_id: int | None = None


class UserUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role_id: int | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class AuditLogOut(ORMModel):
    id: int
    username: str | None = None
    action: str
    target: str | None = None
    detail: str | None = None
    ip: str | None = None
    created_at: datetime


TokenOut.model_rebuild()
