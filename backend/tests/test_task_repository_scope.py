"""Repository task authorization is checked on API writes and saved execution."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, or_, select

from app.core.security import hash_password
from app.models import GithubRepository, Role, ScheduledTask, TaskRecord, User
from app.services.scheduler import scheduler_service


def _task(task_type="github_check_all", payload=None):
    return {"name": f"task-scope-{uuid.uuid4().hex}", "task_type": task_type,
            "schedule_kind": "interval", "interval_seconds": 600, "enabled": False,
            "max_retries": 0, "payload": payload or {}}


@pytest.fixture
async def task_scope(client, db):
    role = await db.scalar(select(Role).where(Role.name == "operator"))
    suffix = uuid.uuid4().hex[:12]
    users = [User(username=f"task-{kind}-{suffix}", role_id=role.id,
                  password_hash=hash_password("task-scope-password")) for kind in ("owner", "other")]
    db.add_all(users)
    await db.flush()
    repos = [GithubRepository(owner="task-scope", name=f"{kind}-{suffix}", full_name=f"task-scope/{kind}-{suffix}",
                              html_url=f"https://github.com/task-scope/{kind}-{suffix}", owner_user_id=owner_id)
             for kind, owner_id in (("own", users[0].id), ("other", users[1].id), ("global", None))]
    db.add_all(repos)
    await db.commit()
    login = await client.post("/api/auth/login", json={"username": users[0].username, "password": "task-scope-password"})
    assert login.status_code == 200, login.text
    try:
        yield users, repos, {"Authorization": f"Bearer {login.json()['access_token']}"}
    finally:
        await db.execute(delete(ScheduledTask).where(ScheduledTask.created_by.in_([u.username for u in users])))
        await db.execute(delete(GithubRepository).where(GithubRepository.id.in_([r.id for r in repos])))
        await db.execute(delete(User).where(User.id.in_([u.id for u in users])))
        await db.commit()


@pytest.mark.parametrize("endpoint", ["/api/tasks", "/api/tasks/preview"])
async def test_foreign_repository_is_rejected_before_task_save_or_preview(client, task_scope, endpoint):
    _, repos, headers = task_scope
    response = await client.post(endpoint, headers=headers, json=_task("github_check", {"repository_id": repos[1].id}))
    assert response.status_code == 403, response.text


async def test_other_users_repository_task_cannot_be_read_or_triggered(client, db, task_scope, monkeypatch):
    users, repos, headers = task_scope
    async def checked(*args):
        return {"ok": True, "new_releases": 0}

    monkeypatch.setattr("app.services.github.monitor.check_repository", checked)
    task = ScheduledTask(**_task("github_check", {"repository_id": repos[1].id}), created_by=users[1].username)
    db.add(task)
    await db.flush()
    record = TaskRecord(task_id=task.id, task_name=task.name, status="success", result={"private": "task result"})
    db.add(record)
    await db.commit()
    for method, path, body in (("post", "run", None), ("post", "toggle", None),
                               ("put", "", {"payload": {"repository_id": repos[0].id}}), ("delete", "", None)):
        response = await client.request(method, f"/api/tasks/{task.id}" + (f"/{path}" if path else ""),
                                        headers=headers, json=body)
        assert response.status_code == 403, response.text
    listed = await client.get("/api/tasks?page_size=100", headers=headers)
    assert task.id not in {row["id"] for row in listed.json()["items"]}
    history = await client.get(f"/api/tasks/records?task_id={task.id}", headers=headers)
    assert history.json()["items"] == []


async def test_scheduled_check_all_filters_repositories_before_network(client, db, task_scope, monkeypatch):
    users, repos, headers = task_scope
    called = []

    async def checked(_db, repo):
        called.append(repo.id)
        return {"ok": True, "new_releases": 0}

    monkeypatch.setattr("app.services.github.monitor.check_repository", checked)
    created = await client.post("/api/tasks", headers=headers, json=_task())
    assert created.status_code == 201, created.text
    record = await scheduler_service.execute_task(created.json()["id"], trigger="schedule")
    assert record.status == "success", record.error
    assert repos[0].id in called and repos[2].id in called
    assert repos[1].id not in called, "A saved task must not use another owner's private token"
    expected = set(await db.scalars(select(GithubRepository.id).where(or_(
        GithubRepository.owner_user_id == users[0].id, GithubRepository.owner_user_id.is_(None),
    ))))
    assert set(called) <= expected


async def test_saved_task_rechecks_repository_owner_and_active_creator(client, db, task_scope, monkeypatch):
    users, repos, headers = task_scope
    created = await client.post("/api/tasks", headers=headers,
                                json=_task("github_check", {"repository_id": repos[0].id}))
    assert created.status_code == 201
    called = []

    async def checked(*args):
        called.append(True)
        return {"ok": True}

    monkeypatch.setattr("app.services.github.monitor.check_repository", checked)
    repos[0].owner_user_id = users[1].id
    await db.commit()
    denied = await scheduler_service.execute_task(created.json()["id"], trigger="schedule")
    assert denied.status == "failed" and "无权" in denied.error
    repos[0].owner_user_id = users[0].id
    users[0].is_active = False
    await db.commit()
    revoked = await scheduler_service.execute_task(created.json()["id"], trigger="queue")
    assert revoked.status == "failed" and "失效" in revoked.error
    assert called == []


async def test_payload_cannot_forge_trusted_repository_scope(client, task_scope):
    _, repos, headers = task_scope
    response = await client.post("/api/tasks", headers=headers,
                                 json=_task("github_check", {"repository_id": repos[0].id,
                                                             "_repository_scope": [repos[1].id]}))
    assert response.status_code == 422, response.text


async def test_null_update_and_legacy_invalid_toggle_fail_before_mutation(client, admin_headers, db):
    task = ScheduledTask(**_task("health_check"))
    db.add(task)
    await db.commit()
    null_update = await client.put(f"/api/tasks/{task.id}", headers=admin_headers, json={"enabled": None, "payload": None})
    assert null_update.status_code == 422, null_update.text
    task.payload = {"_repository_scope": [1]}
    await db.commit()
    toggle = await client.post(f"/api/tasks/{task.id}/toggle", headers=admin_headers)
    assert toggle.status_code == 422, toggle.text
    await db.refresh(task)
    assert not task.enabled
    await db.delete(task)
    await db.commit()


async def test_legacy_invalid_task_cannot_bypass_validation_in_scheduler(client, db, monkeypatch):
    task = ScheduledTask(**_task("online_check", {"notify_account_id": [1], "notify_group": 900001}))
    db.add(task)
    await db.commit()
    called = []

    async def should_not_run(_payload):
        called.append(True)
        return {}

    monkeypatch.setitem(__import__("app.services.scheduler", fromlist=["TASK_HANDLERS"]).TASK_HANDLERS,
                        "online_check", should_not_run)
    record = await scheduler_service.execute_task(task.id, trigger="schedule")
    assert record.status == "failed"
    assert called == []
    await db.delete(task)
    await db.commit()
