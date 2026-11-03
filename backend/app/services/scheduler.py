"""自动化任务中心：APScheduler 调度 + 数据库持久化 + 执行记录 + 防并发 + 失败重试。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Account, GithubRepository, ScheduledTask, TaskRecord
from app.services.logs import write_log
from app.services.task_queue import redis_task_queue

logger = logging.getLogger("qbot.scheduler")


# ---------------------------------------------------------------------------
# 任务实现
# ---------------------------------------------------------------------------
async def _task_github_check(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.github.monitor import check_all_repositories, check_repository

    async with SessionLocal() as db:
        repo_id = payload.get("repository_id")
        if repo_id:
            repo = await db.get(GithubRepository, int(repo_id))
            if not repo:
                raise ValueError(f"仓库 {repo_id} 不存在")
            result = await check_repository(db, repo)
            return {"checked": 1, "new_releases": result.get("new_releases", 0), "ok": result.get("ok")}
        results = await check_all_repositories(db, only_enabled=True)
        return {
            "checked": len(results),
            "new_releases": sum(int(r.get("new_releases") or 0) for r in results),
            "failed": len([r for r in results if not r.get("ok")]),
        }


async def _task_group_message(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.account_manager import account_manager

    account_id = int(payload.get("account_id") or 0)
    group_number = int(payload.get("group_number") or 0)
    content = str(payload.get("content") or "").strip()
    if not account_id or not group_number or not content:
        raise ValueError("任务缺少 account_id / group_number / content")
    result = await account_manager.send_group_message(account_id, group_number, content)
    return {"message_id": (result.get("data") or {}).get("message_id"), "group": group_number}


async def _task_group_announcement(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.account_manager import account_manager

    account_id = int(payload.get("account_id") or 0)
    group_number = int(payload.get("group_number") or 0)
    content = str(payload.get("content") or "").strip()
    if not account_id or not group_number or not content:
        raise ValueError("任务缺少 account_id / group_number / content")
    await account_manager.invoke(
        account_id, "set_group_announce", group_id=group_number, content=content
    )
    if payload.get("also_send_message", True):
        await account_manager.send_group_message(account_id, group_number, content)
    return {"group": group_number, "announcement": True}


async def _task_online_check(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.account_manager import account_manager

    async with SessionLocal() as db:
        accounts = list(await db.scalars(select(Account).where(Account.enabled.is_(True))))
        offline = [a for a in accounts if not account_manager.is_online(a.id)]
        if offline:
            await write_log(
                db,
                level="WARNING",
                category="task",
                message="在线检查：发现离线账号 " + "、".join(f"{a.name}({a.qq_number})" for a in offline),
            )
            notify_account = payload.get("notify_account_id")
            notify_group = payload.get("notify_group")
            if notify_account and notify_group:
                with_suppress = "、".join(a.name for a in offline)
                try:
                    await account_manager.send_group_message(
                        int(notify_account), int(notify_group), f"【账号离线告警】\n{with_suppress}"
                    )
                except Exception as exc:  # noqa: BLE001
                    await write_log(db, level="ERROR", category="task", message=f"离线告警发送失败：{exc}")
        return {"total": len(accounts), "offline": len(offline)}


async def _task_health_check(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.system import collect_system_stats

    stats = await collect_system_stats()
    async with SessionLocal() as db:
        await write_log(
            db,
            level="INFO" if stats["db_ok"] else "ERROR",
            category="task",
            message=f"健康检查：DB={'正常' if stats['db_ok'] else '异常'}，Redis={'正常' if stats['redis_ok'] else '未启用/异常'}，CPU={stats['cpu_percent']}%，内存={stats['memory_percent']}%",
            context={k: v for k, v in stats.items() if isinstance(v, (int, float, bool, str))},
        )
    return {"db_ok": stats["db_ok"], "redis_ok": stats["redis_ok"], "cpu": stats["cpu_percent"]}


async def _task_ai_summary(payload: dict[str, Any]) -> dict[str, Any]:
    from app.models import Message
    from app.services.ai import service as ai_service
    from app.services.account_manager import account_manager

    account_id = int(payload.get("account_id") or 0)
    group_number = int(payload.get("group_number") or 0)
    hours = int(payload.get("hours") or 12)
    if not group_number:
        raise ValueError("AI 总结任务缺少 group_number")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with SessionLocal() as db:
        rows = await db.scalars(
            select(Message)
            .where(Message.qq_group == group_number, Message.created_at >= since, Message.direction == "in")
            .order_by(Message.id.desc())
            .limit(200)
        )
        messages = list(reversed(list(rows)))
        if not messages:
            return {"messages": 0, "summary": ""}
        transcript = "\n".join(f"{m.sender_name}: {m.content}" for m in messages if m.content)[-6000:]
        model = await ai_service.resolve_model(db, account_id=account_id or None, group_number=group_number)
        if not model:
            raise ValueError("没有可用的 AI 模型")
        result, error, _ = await ai_service.chat_once(
            db,
            model,
            [{"role": "user", "content": f"请总结以下群聊记录（{hours} 小时内）：\n{transcript}"}],
            system="你是群聊总结助手，输出条理清晰的中文摘要，包含主要话题、重要结论和待办事项。",
        )
        if not result:
            raise RuntimeError(f"AI 总结失败：{error}")
        summary = result.content.strip()
        if payload.get("send_to_group", True) and account_id:
            await account_manager.send_group_message(account_id, group_number, f"【群聊总结】\n{summary}")
        return {"messages": len(messages), "summary": summary[:500]}


async def _task_backup(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.backup import backup_database

    path = await backup_database()
    return {"backup": str(path)}


async def _task_push_retry(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.github.notify import retry_failed_pushes

    async with SessionLocal() as db:
        stats = await retry_failed_pushes(db, limit=int(payload.get("limit") or 20))
    return stats


TASK_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "github_check": _task_github_check,
    "github_check_all": _task_github_check,
    "group_message": _task_group_message,
    "group_announcement": _task_group_announcement,
    "online_check": _task_online_check,
    "health_check": _task_health_check,
    "ai_summary": _task_ai_summary,
    "backup": _task_backup,
    "push_retry": _task_push_retry,
}


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------
class SchedulerService:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
        self._locks: dict[str, asyncio.Lock] = {}
        self._started = False

    @property
    def running(self) -> bool:
        return self._started and self.scheduler.running

    def job_count(self) -> int:
        return len(self.scheduler.get_jobs()) if self.scheduler.running else 0

    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        self.scheduler.start()
        self._started = True
        await self.reload()
        logger.info("调度器已启动，已加载 %s 个任务", self.job_count())

    async def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False

    async def reload(self) -> None:
        async with SessionLocal() as db:
            tasks = list(await db.scalars(select(ScheduledTask)))
            repos = list(await db.scalars(select(GithubRepository).where(GithubRepository.monitor_enabled.is_(True))))
        for task in tasks:
            self.schedule_task(task)
        for repo in repos:
            self.schedule_repo_poll(repo)
        logger.info("调度任务已重载：%s 个自定义任务，%s 个仓库轮询", len(tasks), len(repos))

    # ------------------------------------------------------------------
    def _add(self, job_id: str, func: Callable, trigger, kwargs: dict[str, Any] | None = None) -> None:
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        self.scheduler.add_job(func, trigger, id=job_id, replace_existing=True, kwargs=kwargs or {})

    def schedule_task(self, task: ScheduledTask) -> None:
        if not task.enabled:
            self.unschedule_task(task.id)
            return
        if not self.scheduler.running:
            # 调度器尚未启动时只落库，start() → reload() 会统一加载
            return
        trigger = self._build_trigger(task)
        if trigger is None:
            logger.warning("任务 %s 的触发器配置无效，已跳过", task.name)
            return
        self._add(f"task:{task.id}", self._execute_job, trigger, {"task_id": task.id})

    def _build_trigger(self, task: ScheduledTask):
        if task.schedule_kind == "cron" and task.cron_expr:
            try:
                return CronTrigger.from_crontab(task.cron_expr, timezone=settings.scheduler_timezone)
            except ValueError as exc:
                logger.warning("cron 表达式无效：%s (%s)", task.cron_expr, exc)
                return None
        interval = task.interval_seconds or 300
        return IntervalTrigger(seconds=interval, timezone=settings.scheduler_timezone)

    def unschedule_task(self, task_id: int) -> None:
        job = self.scheduler.get_job(f"task:{task_id}")
        if job:
            self.scheduler.remove_job(f"task:{task_id}")

    def schedule_repo_poll(self, repo: GithubRepository, *, replace: bool = True) -> None:
        job_id = f"repo:{repo.id}"
        if not repo.monitor_enabled:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return
        if not self.scheduler.running:
            return
        if self.scheduler.get_job(job_id) and not replace:
            return
        self._add(
            job_id,
            self._poll_repo,
            IntervalTrigger(seconds=max(60, repo.poll_interval_seconds), timezone=settings.scheduler_timezone),
            {"repo_id": repo.id},
        )

    def unschedule_repo(self, repo_id: int) -> None:
        job = self.scheduler.get_job(f"repo:{repo_id}")
        if job:
            self.scheduler.remove_job(f"repo:{repo_id}")

    # ------------------------------------------------------------------
    async def _poll_repo(self, repo_id: int) -> None:
        from app.services.github.monitor import check_repository

        lock = self._locks.setdefault(f"repo:{repo_id}", asyncio.Lock())
        if lock.locked():
            logger.info("仓库 %s 上一次检查尚未结束，跳过本次", repo_id)
            return
        async with lock:
            async with SessionLocal() as db:
                repo = await db.get(GithubRepository, repo_id)
                if not repo or not repo.monitor_enabled:
                    return
                try:
                    await check_repository(db, repo)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("仓库轮询失败: %s", exc)

    async def _execute_job(self, task_id: int) -> None:
        if redis_task_queue.enabled:
            try:
                await redis_task_queue.enqueue(task_id, trigger="schedule")
                return
            except Exception as exc:  # noqa: BLE001
                # Redis is optional: a broker outage must not drop scheduled work.
                logger.warning("Redis 任务队列不可用，回退本地执行：%s", exc)
        await self.execute_task(task_id, trigger="schedule")

    async def execute_task(self, task_id: int, *, trigger: str = "manual") -> TaskRecord:
        lock = self._locks.setdefault(f"task:{task_id}", asyncio.Lock())
        if lock.locked():
            logger.info("任务 %s 正在执行，跳过重复触发", task_id)
            async with SessionLocal() as db:
                record = TaskRecord(task_id=task_id, trigger=trigger, status="failed", error="上一次执行尚未结束，已跳过")
                record.finished_at = datetime.now(timezone.utc)
                db.add(record)
                await db.commit()
                return record
        async with lock:
            return await self._run_task(task_id, trigger)

    async def _run_task(self, task_id: int, trigger: str) -> TaskRecord:
        async with SessionLocal() as db:
            task = await db.get(ScheduledTask, task_id)
            if not task:
                raise ValueError("任务不存在")
            handler = TASK_HANDLERS.get(task.task_type)
            attempt = 0
            record: TaskRecord | None = None
            while True:
                record = TaskRecord(
                    task_id=task.id, task_name=task.name, trigger=trigger, status="running", retries=attempt
                )
                db.add(record)
                await db.commit()
                await db.refresh(record)
                started = datetime.now(timezone.utc)
                result: dict[str, Any] | None = None
                try:
                    if not handler:
                        raise ValueError(f"未知任务类型：{task.task_type}")
                    result = await asyncio.wait_for(handler(task.payload or {}), timeout=task.timeout_seconds)
                    record.status = "success"
                except Exception as exc:  # noqa: BLE001
                    record.status = "failed"
                    record.error = f"{type(exc).__name__}: {exc}"[:1000]
                finished = datetime.now(timezone.utc)
                record.finished_at = finished
                record.duration_ms = int((finished - started).total_seconds() * 1000)
                record.result = result
                task.last_run_at = started
                task.last_status = record.status
                task.last_error = record.error
                task.total_runs += 1
                if record.status == "failed":
                    task.total_failures += 1
                job = self.scheduler.get_job(f"task:{task.id}") if self.scheduler.running else None
                if job and job.next_run_time:
                    task.next_run_at = job.next_run_time
                await db.commit()
                await write_log(
                    db,
                    level="INFO" if record.status == "success" else "ERROR",
                    category="task",
                    message=f"任务「{task.name}」执行" + ("成功" if record.status == "success" else "失败")
                    + (f"：{record.error}" if record.error else ""),
                    context={"task_id": task.id, "type": task.task_type, "duration_ms": record.duration_ms},
                )
                if record.status == "failed" and attempt < task.max_retries:
                    attempt += 1
                    await asyncio.sleep(min(5 * attempt, 30))
                    continue
                return record


scheduler_service = SchedulerService()
