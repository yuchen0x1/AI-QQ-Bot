"""Validate saved task inputs and resolve current repository authorization."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, GithubRepository, Group, ScheduledTask, User

REPOSITORY_TASK_TYPES = frozenset({"github_check", "github_check_all", "push_retry"})


class StrictPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class GroupPayload(StrictPayload):
    account_id: int = Field(gt=0)
    group_number: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=4000)
    also_send_message: bool = True


class SummaryPayload(StrictPayload):
    account_id: int = Field(gt=0)
    group_number: int = Field(gt=0)
    hours: int = Field(default=12, ge=1, le=168)
    send_to_group: bool = True


class RepositoryPayload(StrictPayload):
    repository_id: int | None = Field(default=None, gt=0)


class BackupPayload(StrictPayload):
    keep: int = Field(default=14, ge=1, le=365)


class RetryPayload(StrictPayload):
    limit: int = Field(default=20, ge=1, le=200)


class OnlinePayload(StrictPayload):
    notify_account_id: int | None = Field(default=None, gt=0)
    notify_group: int | None = Field(default=None, gt=0)


class RetentionPayload(StrictPayload):
    days: int | None = Field(default=None, ge=0, le=3650)


def is_administrator(user: User) -> bool:
    return "*" in user.permission_set


def visible_task_condition(user: User):
    if is_administrator(user):
        return None
    return or_(ScheduledTask.task_type.not_in(REPOSITORY_TASK_TYPES), ScheduledTask.created_by == user.username)


def require_task_access(task: ScheduledTask, user: User) -> None:
    if task.task_type in REPOSITORY_TASK_TYPES and not is_administrator(user) and task.created_by != user.username:
        raise PermissionError("无权访问其他用户的仓库任务")


async def repository_scope(db: AsyncSession, user: User) -> list[int]:
    query = select(GithubRepository.id).where(GithubRepository.archived_at.is_(None))
    if not is_administrator(user):
        query = query.where(or_(GithubRepository.owner_user_id == user.id, GithubRepository.owner_user_id.is_(None)))
    return list(await db.scalars(query))


async def validate_payload(task_type: str, payload: dict, db: AsyncSession, user: User | None = None) -> None:
    schema = {
        "group_message": GroupPayload, "group_announcement": GroupPayload,
        "ai_summary": SummaryPayload, "github_check": RepositoryPayload,
        "github_check_all": StrictPayload, "backup": BackupPayload, "push_retry": RetryPayload,
        "online_check": OnlinePayload, "clean_expired_data": RetentionPayload,
        "health_check": StrictPayload,
    }.get(task_type)
    if schema is None:
        raise ValueError("不支持的任务类型")
    schema.model_validate(payload)
    if task_type in {"group_message", "group_announcement", "ai_summary"}:
        account = await db.get(Account, payload["account_id"])
        group = await db.scalar(select(Group.id).where(
            Group.account_id == payload["account_id"], Group.group_number == payload["group_number"],
        ))
        if account is None or group is None:
            raise ValueError("请选择该账号已登记的群聊（内部映射 ID）")
        if task_type == "group_announcement" and account.protocol == "qq_official":
            raise ValueError("QQ 官方适配器不支持发布群公告，请使用定时群消息")
        if task_type in {"group_message", "group_announcement"} and not payload["content"].strip():
            raise ValueError("任务消息内容不能为空")
    if task_type == "github_check" and payload.get("repository_id"):
        repo = await db.get(GithubRepository, payload["repository_id"])
        if repo is None or repo.archived_at is not None:
            raise ValueError("仓库不存在或已归档")
        if user is not None and repo.id not in await repository_scope(db, user):
            raise PermissionError("无权检查此仓库")
    if task_type in REPOSITORY_TASK_TYPES and user is not None:
        required = "push:manage" if task_type == "push_retry" else "github:manage"
        if not is_administrator(user) and required not in user.permission_set:
            raise PermissionError(f"缺少权限: {required}")
    if task_type == "online_check":
        account_id, group_id = payload.get("notify_account_id"), payload.get("notify_group")
        if bool(account_id) != bool(group_id):
            raise ValueError("告警账号与告警群必须同时填写")
        if account_id and not await db.scalar(select(Group.id).where(Group.account_id == account_id, Group.group_number == group_id)):
            raise ValueError("告警群未在该账号登记")


async def execution_payload(db: AsyncSession, task: ScheduledTask) -> dict:
    """Re-authorize persisted repository tasks; payload cannot choose its actor."""
    user = None
    if task.task_type in REPOSITORY_TASK_TYPES:
        user = await db.scalar(select(User).where(User.username == task.created_by, User.is_active.is_(True)))
        if user is None or not (is_administrator(user) or "task:manage" in user.permission_set):
            raise PermissionError("仓库任务创建者已失效，请由管理员重新创建并授权")
    await validate_payload(task.task_type, task.payload, db, user)
    payload = dict(task.payload)
    if user is not None:
        payload["_repository_scope"] = await repository_scope(db, user)
    return payload
