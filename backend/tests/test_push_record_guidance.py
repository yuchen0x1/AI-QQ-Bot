"""Delivery guidance reflects the real automatic retry budget and state."""

from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.models import GithubRepository, PushRecord, PushRule
from app.services.github import notify


@pytest.fixture
async def delivery_scope(client, db, mock_account):
    suffix = uuid.uuid4().hex
    repo = GithubRepository(owner="delivery-guidance", name=suffix, full_name=f"delivery-guidance/{suffix}",
                            html_url=f"https://github.com/delivery-guidance/{suffix}")
    db.add(repo)
    await db.flush()
    rule = PushRule(repository_id=repo.id, account_id=mock_account["id"], qq_group=900001)
    db.add(rule)
    await db.commit()
    try:
        yield repo, rule
    finally:
        await db.delete(repo)
        await db.commit()


async def _list(client, admin_headers, repo_id):
    response = await client.get("/api/github/push-records", headers=admin_headers,
                                params={"repo_id": repo_id, "page_size": 100})
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


async def test_push_record_categories_actions_and_terminal_states(client, admin_headers, db, delivery_scope, monkeypatch):
    repo, rule = delivery_scope
    monkeypatch.setattr(settings, "push_max_retries", 3)
    cases = [
        ("failed", "upstream timeout", 0, "timeout", False),
        ("failed", "账号不在线，无法发送消息", 1, "connection", False),
        ("failed", "403 forbidden: no permission", 1, "authorization", False),
        ("failed", "推送规则绑定的 QQ 账号不存在", 1, "configuration", False),
        ("failed", "HTTP 429: too many requests", 3, "rate_limit", True),
        ("failed", "unexpected delivery failure", 3, "execution", True),
        ("cancelled", "推送目标或启用状态已改变，取消旧通知", 3, "cancelled", False),
        ("success", None, 4, None, False),
        ("pending", None, 0, None, False),
    ]
    records = [PushRecord(repository_id=repo.id, rule_id=rule.id, account_id=rule.account_id,
                          qq_group=rule.qq_group, content=f"guidance-{index}", status=status,
                          error=error, retries=retries)
               for index, (status, error, retries, _, _) in enumerate(cases)]
    db.add_all(records)
    await db.commit()
    listed = await _list(client, admin_headers, repo.id)
    for record, (status, error, retries, category, exhausted) in zip(records, cases, strict=True):
        item = listed[record.id]
        assert item["status"] == status and item["error"] == error and item["retries"] == retries
        assert item["error_category"] == category
        assert item["retries_exhausted"] is exhausted
        assert item["next_action"] is None if status == "success" else bool(item["next_action"])
        if exhausted:
            assert "耗尽" in item["next_action"] and "手动" in item["next_action"]


async def test_guidance_tracks_real_retry_threshold_and_manual_success(client, admin_headers, db, delivery_scope, monkeypatch):
    repo, rule = delivery_scope
    monkeypatch.setattr(settings, "push_max_retries", 2)
    record = PushRecord(repository_id=repo.id, rule_id=rule.id, account_id=rule.account_id,
                        qq_group=rule.qq_group, status="failed", retries=1, error="timeout")
    db.add(record)
    await db.commit()
    assert not (await _list(client, admin_headers, repo.id))[record.id]["retries_exhausted"]

    async def unavailable(*args):
        raise RuntimeError("timeout")

    monkeypatch.setattr(notify, "send_push_record", unavailable)
    retried = await notify.retry_failed_pushes(db, repository_ids=[repo.id])
    assert retried == {"attempted": 1, "success": 0, "failed": 1}
    exhausted = (await _list(client, admin_headers, repo.id))[record.id]
    assert exhausted["retries"] == 2 and exhausted["retries_exhausted"]
    assert await notify.retry_failed_pushes(db, repository_ids=[repo.id]) == {"attempted": 0, "success": 0, "failed": 0}

    async def delivered(*args):
        return {"data": {"message_id": 610001}}

    monkeypatch.setattr(notify, "send_push_record", delivered)
    await notify.resend_record(db, record)
    recovered = (await _list(client, admin_headers, repo.id))[record.id]
    assert recovered["status"] == "success" and recovered["retries"] == 3
    assert not recovered["retries_exhausted"] and recovered["error_category"] is None
    assert recovered["next_action"] is None


async def test_offline_does_not_exhaust_retry_budget_and_zero_disables_automatic_retry(client, admin_headers, db, delivery_scope, monkeypatch):
    repo, rule = delivery_scope
    record = PushRecord(repository_id=repo.id, rule_id=rule.id, account_id=rule.account_id,
                        qq_group=rule.qq_group, status="failed", retries=1, error="账号不在线")
    db.add(record)
    await db.commit()
    monkeypatch.setattr(settings, "push_max_retries", 2)
    monkeypatch.setattr("app.services.account_manager.account_manager.is_online", lambda account_id: False)
    assert await notify.retry_failed_pushes(db, repository_ids=[repo.id]) == {"attempted": 0, "success": 0, "failed": 0}
    waiting = (await _list(client, admin_headers, repo.id))[record.id]
    assert waiting["retries"] == 1 and not waiting["retries_exhausted"]
    monkeypatch.setattr(settings, "push_max_retries", 0)
    disabled = (await _list(client, admin_headers, repo.id))[record.id]
    assert disabled["retries_exhausted"] and "关闭" in disabled["next_action"]
