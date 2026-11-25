"""自动化任务中心 API。"""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.api.pagination import PageParam, PageSizeParam
from app.core.config import settings
from app.db.session import get_db
from app.models import ScheduledTask, TaskRecord, User
from app.schemas.common import MessageOut, Page
from app.schemas.task import TaskCreate, TaskOut, TaskRecordOut, TaskUpdate
from app.services.logs import audit
from app.services.scheduler import TASK_HANDLERS, scheduler_service, validate_task_schedule
from app.services import task_policy

router = APIRouter(prefix="/tasks", tags=["自动化任务"])


async def validate_payload(task_type: str, payload: dict, db: AsyncSession, user: User) -> None:
    try:
        await task_policy.validate_payload(task_type, payload, db, user)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def require_task_access(task: ScheduledTask, user: User) -> None:
    try:
        task_policy.require_task_access(task, user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def error_guidance(error: str | None, retries: int = 0, max_retries: int = 0) -> dict:
    text = (error or "").lower()
    if not text:
        return {"category": None, "retries_exhausted": False, "next_action": None}
    if any(word in text for word in ("timeout", "超时")):
        category, action = "timeout", "检查外部服务响应与任务超时设置后重试"
    elif any(word in text for word in ("离线", "offline", "连接", "connect")):
        category, action = "connection", "先恢复账号或网络连接，再手动试运行"
    elif any(word in text for word in ("参数", "缺少", "不存在", "valueerror", "unsupported", "不支持")):
        category, action = "configuration", "编辑任务并校验参数、目标与账号能力"
    elif any(word in text for word in ("401", "403", "权限", "token", "认证")):
        category, action = "authorization", "检查凭据和目标资源授权后重试"
    else:
        category, action = "execution", "查看错误详情与相关日志，确认副作用后再重试"
    return {"category": category, "retries_exhausted": retries >= max_retries, "next_action": action}


@router.get("/types")
async def task_types(_: User = Depends(require("task:view"))):
    descriptions = {
        "github_check": "检查授权仓库更新（payload.repository_id），不填则检查当前用户授权仓库",
        "github_check_all": "检查当前用户授权且启用监控的仓库",
        "group_message": "定时向指定群发送消息（account_id / group_number / content）",
        "group_announcement": "定时发布群公告（account_id / group_number / content）",
        "online_check": "检查账号在线状态，可选告警到群（notify_account_id / notify_group）",
        "ai_summary": "AI 总结群聊（account_id / group_number / hours）",
        "health_check": "系统健康检查（数据库、Redis、资源）",
        "backup": "数据库备份",
        "push_retry": "重试失败的推送记录",
    }
    return [{"value": key, "label": descriptions.get(key, key), "implemented": key in TASK_HANDLERS} for key in descriptions]


@router.post("/preview")
async def preview_task(
    payload: TaskCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require("task:manage")),
):
    try:
        validate_task_schedule(schedule_kind=payload.schedule_kind, interval_seconds=payload.interval_seconds, cron_expr=payload.cron_expr)
        await validate_payload(payload.task_type, payload.payload, db, user)
        trigger = (CronTrigger.from_crontab(payload.cron_expr or "", timezone=settings.scheduler_timezone)
                   if payload.schedule_kind == "cron"
                   else IntervalTrigger(seconds=payload.interval_seconds or 300, timezone=settings.scheduler_timezone))
        now = datetime.now(timezone.utc)
        times = []
        previous = None
        for _ in range(3):
            upcoming = trigger.get_next_fire_time(previous, now)
            if upcoming is None:
                break
            times.append(upcoming.isoformat())
            previous = upcoming
            now = upcoming
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"valid": True, "timezone": settings.scheduler_timezone, "next_runs": times,
            "message": "参数校验通过；预览不会执行任务或产生外部副作用"}


@router.get("", response_model=Page[TaskOut])
async def list_tasks(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    keyword: str | None = None,
    enabled: bool | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("task:view")),
):
    query = select(ScheduledTask)
    scope = task_policy.visible_task_condition(user)
    if scope is not None:
        query = query.where(scope)
    if keyword:
        query = query.where(ScheduledTask.name.ilike(f"%{keyword}%"))
    if enabled is not None:
        query = query.where(ScheduledTask.enabled.is_(enabled))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(ScheduledTask.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[TaskOut.model_validate(t) for t in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require("task:manage"))
):
    if payload.task_type not in TASK_HANDLERS:
        raise HTTPException(status_code=400, detail="不支持的任务类型")
    try:
        validate_task_schedule(
            schedule_kind=payload.schedule_kind,
            interval_seconds=payload.interval_seconds,
            cron_expr=payload.cron_expr,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await validate_payload(payload.task_type, payload.payload, db, user)
    task = ScheduledTask(
        name=payload.name,
        task_type=payload.task_type,
        schedule_kind=payload.schedule_kind,
        interval_seconds=payload.interval_seconds,
        cron_expr=payload.cron_expr,
        payload=payload.payload,
        enabled=payload.enabled,
        max_retries=payload.max_retries,
        timeout_seconds=payload.timeout_seconds,
        created_by=user.username,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    if payload.enabled:
        scheduler_service.schedule_task(task)
    await audit(db, user_id=user.id, username=user.username, action="create_task", target=task.name)
    return TaskOut.model_validate(task)


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int, payload: TaskUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require("task:manage"))
):
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_task_access(task, user)
    data = payload.model_dump(exclude_unset=True)
    if any(value is None for key, value in data.items() if key not in {"interval_seconds", "cron_expr"}):
        raise HTTPException(status_code=422, detail="任务字段不能设为 null")
    try:
        validate_task_schedule(
            schedule_kind=data.get("schedule_kind", task.schedule_kind),
            interval_seconds=data.get("interval_seconds", task.interval_seconds),
            cron_expr=data.get("cron_expr", task.cron_expr),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await validate_payload(task.task_type, data.get("payload", task.payload), db, user)
    for field, value in data.items():
        setattr(task, field, value)
    await db.commit()
    await db.refresh(task)
    if task.enabled:
        scheduler_service.schedule_task(task)
    else:
        scheduler_service.unschedule_task(task.id)
    await audit(db, user_id=user.id, username=user.username, action="update_task", target=task.name)
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", response_model=MessageOut)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("task:manage"))):
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_task_access(task, user)
    name = task.name
    scheduler_service.unschedule_task(task.id)
    await db.delete(task)
    await db.commit()
    await audit(db, user_id=user.id, username=user.username, action="delete_task", target=name)
    return MessageOut(detail=f"任务 {name} 已删除")


@router.post("/{task_id}/toggle", response_model=TaskOut)
async def toggle_task(
    task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("task:manage"))
):
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_task_access(task, user)
    if not task.enabled:
        await validate_payload(task.task_type, task.payload, db, user)
    task.enabled = not task.enabled
    await db.commit()
    await db.refresh(task)
    if task.enabled:
        scheduler_service.schedule_task(task)
    else:
        scheduler_service.unschedule_task(task.id)
    await audit(
        db,
        user_id=user.id,
        username=user.username,
        action="toggle_task",
        target=task.name,
        detail=f"enabled={task.enabled}",
    )
    return TaskOut.model_validate(task)


@router.post("/{task_id}/run")
async def run_task(task_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require("task:manage"))):
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_task_access(task, user)
    await validate_payload(task.task_type, task.payload, db, user)
    record = await scheduler_service.execute_task(task.id, trigger="manual")
    return {
        "ok": record.status == "success",
        "status": record.status,
        "duration_ms": record.duration_ms,
        "result": record.result,
        "error": record.error,
        "record_id": record.id,
        **error_guidance(record.error, record.retries, task.max_retries),
    }


@router.get("/records", response_model=Page[TaskRecordOut])
async def list_records(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    task_id: int | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("task:view")),
):
    query = select(TaskRecord)
    scope = task_policy.visible_task_condition(user)
    if scope is not None:
        query = query.where(TaskRecord.task_id.in_(select(ScheduledTask.id).where(scope)))
    if task_id:
        query = query.where(TaskRecord.task_id == task_id)
    if status:
        query = query.where(TaskRecord.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(await db.scalars(query.order_by(TaskRecord.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    task_ids = {row.task_id for row in rows if row.task_id is not None}
    tasks = {task.id: task for task in await db.scalars(select(ScheduledTask).where(ScheduledTask.id.in_(task_ids)))}
    items = []
    for row in rows:
        item = TaskRecordOut.model_validate(row)
        task = tasks.get(row.task_id)
        for key, value in error_guidance(row.error, row.retries, task.max_retries if task else row.retries).items():
            setattr(item, key, value)
        items.append(item)
    return Page(items=items, total=total, page=page, page_size=page_size)
