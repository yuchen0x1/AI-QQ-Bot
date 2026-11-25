"""Task previews, saved inputs and manual runs share strict validation."""

from __future__ import annotations

import uuid

import pytest

from app.models import Group, ScheduledTask
from app.services.scheduler import scheduler_service


def _task(task_type, payload):
    return {"name": f"payload-boundary-{uuid.uuid4().hex[:8]}", "task_type": task_type,
            "schedule_kind": "interval", "interval_seconds": 600, "enabled": False, "payload": payload}


@pytest.mark.parametrize("endpoint", ["/api/tasks", "/api/tasks/preview"])
async def test_summary_string_false_is_rejected_before_execution(client, admin_headers, mock_account, db, endpoint):
    account_id = mock_account["id"]
    group = Group(account_id=account_id, group_number=444001, name="payload boundary")
    db.add(group)
    await db.commit()
    response = await client.post(endpoint, headers=admin_headers, json=_task("ai_summary", {
        "account_id": account_id, "group_number": group.group_number, "send_to_group": "false",
    }))
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("bad_payload", [
    {"notify_account_id": [1], "notify_group": 900001},
    {"notify_account_id": 1, "notify_group": "900001"},
    {"notify_account_id": True, "notify_group": 900001},
])
async def test_online_check_rejects_malformed_target_ids(client, admin_headers, bad_payload):
    response = await client.post("/api/tasks/preview", headers=admin_headers, json=_task("online_check", bad_payload))
    assert response.status_code == 422, response.text


async def test_existing_invalid_task_cannot_bypass_validation_via_manual_run(client, admin_headers, mock_account, db, monkeypatch):
    account_id = mock_account["id"]
    group = Group(account_id=account_id, group_number=444002, name="legacy malformed task")
    db.add(group)
    await db.flush()
    task = ScheduledTask(**_task("ai_summary", {
        "account_id": account_id, "group_number": group.group_number, "send_to_group": "false",
    }))
    db.add(task)
    await db.commit()
    invoked = []

    async def should_not_execute(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("invalid task reached execution")

    monkeypatch.setattr(scheduler_service, "execute_task", should_not_execute)
    response = await client.post(f"/api/tasks/{task.id}/run", headers=admin_headers)
    assert response.status_code == 422, response.text
    assert invoked == []


async def test_strict_boolean_false_is_saved_without_coercion(client, admin_headers, mock_account, db):
    account_id = mock_account["id"]
    group = Group(account_id=account_id, group_number=444003, name="typed task")
    db.add(group)
    await db.commit()
    response = await client.post("/api/tasks", headers=admin_headers, json=_task("ai_summary", {
        "account_id": account_id, "group_number": group.group_number, "send_to_group": False,
    }))
    assert response.status_code == 201, response.text
    assert response.json()["payload"]["send_to_group"] is False
