"""Email settings, real failure wiring, durable retries and honest first-run guidance."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import decrypt_secret
from app.models import EmailAlert, SystemSetting
from app.services import agent_mail, email_alerts
from app.services.agent_mail import send as send_through_cli
from app.services.logs import write_log


@pytest.fixture(autouse=True)
async def isolated_mail(db, monkeypatch):
    async def accepted(*args, **kwargs):
        return None
    monkeypatch.setattr(agent_mail, "send", accepted)
    await email_alerts.put_setting(db, email_alerts.CONFIG_KEY, dict(email_alerts.DEFAULT), secret=True)
    yield
    await email_alerts.put_setting(db, email_alerts.CONFIG_KEY, dict(email_alerts.DEFAULT), secret=True)


async def enable(client, headers, **changes):
    value = {"enabled": True, "provider": "agentmail", "recipient": "owner@example.com", "categories": ["task", "push"], **changes}
    response = await client.put('/api/system/email', headers=headers, json=value)
    assert response.status_code == 200, response.text
    return response.json()


async def test_email_config_is_editable_and_smtp_secret_never_echoed(client, admin_headers, db):
    state = await enable(client, admin_headers, provider="smtp", smtp_host="smtp.example.com", smtp_sender="bot@example.com", smtp_password="unit-mail-secret")
    assert state["has_smtp_password"] and "smtp_password_enc" not in state
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == email_alerts.CONFIG_KEY))
    assert row.is_secret and decrypt_secret(row.value["smtp_password_enc"]) == "unit-mail-secret"
    edited = await enable(client, admin_headers, recipient="changed@example.com", provider="smtp", smtp_host="smtp.example.com", smtp_sender="bot@example.com", smtp_password="")
    assert edited["recipient"] == "changed@example.com" and edited["has_smtp_password"]
    assert "unit-mail-secret" not in (await client.get('/api/system/settings', headers=admin_headers)).text
    invalid = await client.put('/api/system/email', headers=admin_headers, json={"recipient":"a@example.com\nBcc: other@example.com"})
    assert invalid.status_code == 422


async def test_failure_log_is_queued_deduplicated_and_accepted(client, admin_headers, db):
    await enable(client, admin_headers)
    await write_log(db, level="ERROR", category="task", message="任务单测失败 UNIQUE-MAIL-OUTBOX")
    await write_log(db, level="ERROR", category="task", message="任务单测失败 UNIQUE-MAIL-OUTBOX")
    rows = list(await db.scalars(select(EmailAlert).where(EmailAlert.body.contains("UNIQUE-MAIL-OUTBOX"))))
    assert len(rows) == 1
    row = rows[0]
    await email_alerts.dispatch_email_alerts(row.id)
    await db.refresh(row)
    assert row.status == "accepted" and row.attempts == 1 and row.accepted_at


async def test_retry_persists_failures_and_disable_cancels_pending(client, admin_headers, db, monkeypatch):
    await enable(client, admin_headers)
    async def rejected(*args, **kwargs):
        raise ValueError("发信授权已失效")
    monkeypatch.setattr(agent_mail, "send", rejected)
    row = await email_alerts.enqueue(db, title="失败重试", body="test", category="push", force=True)
    await email_alerts.dispatch_email_alerts(row.id)
    await db.refresh(row)
    assert row.status == "retrying" and row.attempts == 1 and "授权" in row.error
    row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await email_alerts.dispatch_email_alerts(row.id)
    await db.refresh(row)
    assert row.attempts == 2
    await enable(client, admin_headers, enabled=False)
    await db.refresh(row)
    assert row.status == "cancelled"


async def test_config_change_does_not_readdress_pending_mail(client, admin_headers, db):
    await enable(client, admin_headers)
    row = await email_alerts.enqueue(db, title="收件人不可改变", body="test", category="task", force=True)
    await enable(client, admin_headers, recipient="new@example.com")
    await email_alerts.dispatch_email_alerts(row.id)
    await db.refresh(row)
    assert row.status == "cancelled" and row.recipient == "owner@example.com"


async def test_crashed_last_attempt_is_reported_without_extra_delivery(client, admin_headers, db):
    await enable(client, admin_headers)
    row = await email_alerts.enqueue(db, title="last attempt interrupted", body="test", category="task", force=True)
    row.status, row.attempts = "sending", 3
    row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    await db.commit()
    await email_alerts.dispatch_email_alerts(row.id)
    await db.refresh(row)
    assert row.status == "failed" and row.attempts == 3
    assert "未确认" in row.error


async def test_agent_auth_status_and_test_mail(client, admin_headers, monkeypatch):
    async def profile():
        return {"connected": True, "sender": "sender@agent.qq.com", "aliases": ["sender@agent.qq.com"]}
    monkeypatch.setattr(agent_mail, "profile", profile)
    state = await client.post('/api/system/email/agent/check', headers=admin_headers)
    assert state.json()["agent"]["sender"] == "sender@agent.qq.com"
    await enable(client, admin_headers)
    result = await client.post('/api/system/email/test', headers=admin_headers)
    assert result.status_code == 200 and result.json()["ok"]
    assert result.json()["status"] == "accepted"


async def test_first_run_progress_is_persistent_but_does_not_fake_readiness(client, admin_headers):
    state = (await client.get('/api/onboarding', headers=admin_headers)).json()
    assert len(state["steps"]) == 5
    await client.put('/api/onboarding', headers=admin_headers, json={"seen":True,"step":4})
    updated = (await client.get('/api/onboarding', headers=admin_headers)).json()
    assert updated["progress"] == {"seen":True,"step":4}
    assert updated["steps"] == state["steps"]
    invalid = await client.put('/api/onboarding', headers=admin_headers, json={"step":99})
    assert invalid.status_code == 422


async def test_confirmation_prompt_is_not_a_send_ack(client, monkeypatch):
    async def unconfirmed(*args, **kwargs):
        return {"ok": True, "data": {"confirmation_required": True}}
    monkeypatch.setattr(agent_mail, "run_cli", unconfirmed)
    with pytest.raises(ValueError, match="未确认"):
        await send_through_cli("owner@example.com", "not accepted yet", "body")


async def test_windows_npm_shim_resolves_native_binary(client, tmp_path, monkeypatch):
    import os
    if os.name != "nt":
        pytest.skip("Windows npm shims only")
    shim = tmp_path / "agently-cli.cmd"
    shim.write_text("test fixture", encoding="utf-8")
    binary = tmp_path / "node_modules/@tencent-qqmail/agently-cli/node_modules/@tencent-qqmail/agently-cli-win32-x64/bin/agently-cli.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fixture, never execute")
    monkeypatch.setattr(agent_mail.settings, "agently_cli_path", str(shim))
    assert agent_mail.executable() == str(binary)
