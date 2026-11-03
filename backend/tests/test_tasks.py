"""自动化任务：创建、立即执行、失败重试、记录、触发器校验、备份。"""

from __future__ import annotations

import httpx


async def test_health_check_task(client: httpx.AsyncClient, admin_headers: dict):
    created = await client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "name": "测试健康检查",
            "task_type": "health_check",
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "payload": {},
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["enabled"] is True

    run = await client.post(f"/api/tasks/{task['id']}/run", headers=admin_headers)
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["ok"] is True
    assert body["status"] == "success"
    assert body["result"]["db_ok"] is True

    records = await client.get(f"/api/tasks/records?task_id={task['id']}", headers=admin_headers)
    assert records.status_code == 200
    assert records.json()["total"] >= 1
    assert records.json()["items"][0]["trigger"] == "manual"

    toggled = await client.post(f"/api/tasks/{task['id']}/toggle", headers=admin_headers)
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False


async def test_task_failure_returns_error(client: httpx.AsyncClient, admin_headers: dict):
    created = await client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "name": "缺少参数的群消息任务",
            "task_type": "group_message",
            "schedule_kind": "interval",
            "interval_seconds": 600,
            "payload": {},
            "enabled": False,
            "max_retries": 0,
        },
    )
    assert created.status_code == 201
    task = created.json()
    run = await client.post(f"/api/tasks/{task['id']}/run", headers=admin_headers)
    assert run.status_code == 200
    body = run.json()
    assert body["ok"] is False
    assert "account_id" in (body["error"] or "")


async def test_cron_validation(client: httpx.AsyncClient, admin_headers: dict):
    bad = await client.post(
        "/api/tasks",
        headers=admin_headers,
        json={"name": "缺少间隔", "task_type": "health_check", "schedule_kind": "interval"},
    )
    assert bad.status_code == 422

    cron = await client.post(
        "/api/tasks",
        headers=admin_headers,
        json={
            "name": "每天9点健康检查",
            "task_type": "health_check",
            "schedule_kind": "cron",
            "cron_expr": "0 9 * * *",
            "payload": {},
            "enabled": True,
        },
    )
    assert cron.status_code == 201, cron.text

    unknown = await client.post(
        "/api/tasks",
        headers=admin_headers,
        json={"name": "未知类型", "task_type": "not_exists", "schedule_kind": "interval", "interval_seconds": 60},
    )
    assert unknown.status_code == 422


async def test_task_persistence_across_reload(client: httpx.AsyncClient, admin_headers: dict, db):
    """任务定义写入数据库，服务重启后由 reload 重新加载（此处验证持久化与触发器可用）。"""
    from app.models import ScheduledTask
    from app.services.scheduler import scheduler_service
    from sqlalchemy import select

    rows = list(await db.scalars(select(ScheduledTask).where(ScheduledTask.enabled.is_(True))))
    assert rows, "应存在已启用的任务"
    for task in rows:
        trigger = scheduler_service._build_trigger(task)
        assert trigger is not None, f"任务 {task.name} 的触发器无效"


async def test_backup_database(client: httpx.AsyncClient, admin_headers: dict):
    resp = await client.post("/api/system/backup", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["path"].endswith(".db")
    listing = await client.get("/api/system/backups", headers=admin_headers)
    assert listing.status_code == 200
    assert any(item["name"] == body["path"].split("\\")[-1].split("/")[-1] for item in listing.json())


async def test_system_settings_and_logs(client: httpx.AsyncClient, admin_headers: dict):
    settings = await client.get("/api/system/settings", headers=admin_headers)
    assert settings.status_code == 200
    assert any(item["key"] == "bot_super_admins" for item in settings.json())

    updated = await client.put(
        "/api/system/settings/bot_super_admins", headers=admin_headers, json={"value": [20001]}
    )
    assert updated.status_code == 200
    assert updated.json()["value"] == [20001]

    logs = await client.get("/api/logs?category=task&page_size=5", headers=admin_headers)
    assert logs.status_code == 200
    assert logs.json()["total"] >= 1

    info = await client.get("/api/system/info", headers=admin_headers)
    assert info.status_code == 200
    assert info.json()["version"] == "1.0.0"
