"""自动化任务中心 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require
from app.api.pagination import PageParam, PageSizeParam
from app.db.session import get_db
from app.models import ScheduledTask, TaskRecord, User
from app.schemas.common import MessageOut, Page
from app.schemas.task import TaskCreate, TaskOut, TaskRecordOut, TaskUpdate
from app.services.logs import audit
from app.services.scheduler import TASK_HANDLERS, scheduler_service

router = APIRouter(prefix="/tasks", tags=["自动化任务"])


@router.get("/types")
async def task_types(_: User = Depends(require("task:view"))):
    descriptions = {
        "github_check": "检查指定仓库更新（payload.repository_id），不填则检查全部",
        "github_check_all": "检查全部启用监控的仓库",
        "group_message": "定时向指定群发送消息（account_id / group_number / content）",
        "group_announcement": "定时发布群公告（account_id / group_number / content）",
        "online_check": "检查账号在线状态，可选告警到群（notify_account_id / notify_group）",
        "ai_summary": "AI 总结群聊（account_id / group_number / hours）",
        "health_check": "系统健康检查（数据库、Redis、资源）",
        "backup": "数据库备份",
        "push_retry": "重试失败的推送记录",
    }
    return [{"value": key, "label": descriptions.get(key, key), "implemented": key in TASK_HANDLERS} for key in descriptions]


@router.get("", response_model=Page[TaskOut])
async def list_tasks(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    keyword: str | None = None,
    enabled: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("task:view")),
):
    query = select(ScheduledTask)
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
    for field, value in payload.model_dump(exclude_unset=True).items():
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
async def run_task(task_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require("task:manage"))):
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    record = await scheduler_service.execute_task(task.id, trigger="manual")
    return {
        "ok": record.status == "success",
        "status": record.status,
        "duration_ms": record.duration_ms,
        "result": record.result,
        "error": record.error,
        "record_id": record.id,
    }


@router.get("/records", response_model=Page[TaskRecordOut])
async def list_records(
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    task_id: int | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require("task:view")),
):
    query = select(TaskRecord)
    if task_id:
        query = query.where(TaskRecord.task_id == task_id)
    if status:
        query = query.where(TaskRecord.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(TaskRecord.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[TaskRecordOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)
