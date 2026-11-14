"""数据保留与备份轮转回归。

清理任务此前只删 4 张表，认证会话/审计/推送记录/AI 会话会无限增长；
定时备份也不轮转，长期运行后 backups/ 无限膨胀。这里锁定修复。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.services.scheduler import _task_backup, _task_clean_expired_data


def _stamp(path, offset: int) -> str:
    path.write_bytes(b"x")
    os.utime(path, (1_700_000_000 + offset, 1_700_000_000 + offset))
    return str(path)


async def _seed_old_rows(db) -> dict[str, int]:
    from app.models import (
        Account,
        AIConversation,
        AIUsageLog,
        AuditLog,
        AuthSession,
        GithubEvent,
        GithubRelease,
        GithubRepository,
        LoginAttempt,
        Message,
        PushRecord,
        PushRule,
        SystemLog,
        TaskRecord,
        User,
    )

    old = datetime.now(timezone.utc) - timedelta(days=90)
    fresh = datetime.now(timezone.utc) - timedelta(days=1)

    account = Account(
        account_id="retention-test", name="retention-test", qq_number=900001, protocol="mock", enabled=False
    )
    db.add(account)
    await db.flush()
    user = await db.scalar(sa.select(User).where(User.username == "admin"))

    # 外键已启用：推送记录种子必须引用真实存在的仓库/规则/发布。
    repo = GithubRepository(
        owner="retention", name="probe", full_name="retention/probe",
        html_url="https://github.com/retention/probe", default_branch="main",
    )
    db.add(repo)
    await db.flush()
    release = GithubRelease(repository_id=repo.id, tag_name="v0.0.1-retention", html_url="https://github.com/retention/probe/releases/tag/v0.0.1-retention")
    db.add(release)
    rule = PushRule(repository_id=repo.id, account_id=account.id, qq_group=1, event_types=["release"])
    db.add_all([release, rule])
    await db.flush()

    msg_old = Message(account_id=account.id, direction="in", created_at=old)
    msg_new = Message(account_id=account.id, direction="in", created_at=fresh)
    db.add_all([msg_old, msg_new])
    db.add(SystemLog(level="INFO", category="test", message="old", created_at=old))
    db.add(TaskRecord(task_name="t", status="success", started_at=old))
    db.add(AIUsageLog(status="success", created_at=old))

    # 已过期 / 已撤销的会话应被清理；仍有效的会话必须保留。
    sess_old = AuthSession(user_id=user.id, jti="old-session", expires_at=old, created_at=old)
    sess_live = AuthSession(
        user_id=user.id,
        jti="live-session",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=fresh,
    )
    db.add_all([sess_old, sess_live])

    db.add(LoginAttempt(username="retention-probe", ip="127.0.0.1", success=False, created_at=old))
    db.add(AuditLog(username="admin", action="x", detail="", ip="127.0.0.1", created_at=old))
    db.add(GithubEvent(repository_id=repo.id, event_type="release", dedupe_key="retention-test-event", payload={}, created_at=old))

    push_done = PushRecord(
        repository_id=repo.id, rule_id=rule.id, release_id=release.id, account_id=account.id, qq_group=1,
        status="success", created_at=old,
    )
    push_pending = PushRecord(
        repository_id=repo.id, rule_id=rule.id, release_id=None, account_id=account.id, qq_group=1,
        status="pending", created_at=old,
    )
    db.add_all([push_done, push_pending])

    conv_old = AIConversation(account_id=account.id, scope="group", group_number=1, last_active_at=old, created_at=old)
    conv_null = AIConversation(
        account_id=account.id, scope="group", group_number=2, last_active_at=None, created_at=old
    )
    conv_new = AIConversation(
        account_id=account.id, scope="group", group_number=3, last_active_at=fresh, created_at=fresh
    )
    db.add_all([conv_old, conv_null, conv_new])

    await db.commit()
    return {
        "account_id": account.id,
        "msg_new": msg_new.id,
        "sess_live": sess_live.id,
        "conv_new": conv_new.id,
        "push_pending": push_pending.id,
    }


async def test_clean_expired_data_covers_growing_tables(db, client) -> None:
    from app.models import AIConversation, AuthSession, LoginAttempt, Message, PushRecord

    ids = await _seed_old_rows(db)
    result = await _task_clean_expired_data({"days": 30})

    assert result["days"] == 30
    for key in (
        "messages", "logs", "task_records", "ai_usage_logs", "auth_sessions",
        "login_attempts", "audit_logs", "github_events", "push_records", "ai_conversations",
    ):
        assert key in result, f"清理结果缺少 {key}"
        assert result[key] >= 1, f"{key} 没有删掉任何过期数据"

    # 未过期/仍在用的数据不能被误删。
    db.expire_all()
    assert await db.get(Message, ids["msg_new"]) is not None
    assert await db.get(AuthSession, ids["sess_live"]) is not None
    assert await db.get(AIConversation, ids["conv_new"]) is not None
    # pending 推送即使过期也要保留，等重试。
    assert await db.get(PushRecord, ids["push_pending"]) is not None
    # 只校验本次种下的旧记录被删；其它用例可能留下"新鲜"的登录失败记录。
    assert (
        await db.scalar(
            sa.select(sa.func.count()).select_from(LoginAttempt).where(LoginAttempt.username == "retention-probe")
        )
        == 0
    )


async def test_clean_expired_data_skips_when_disabled(db, client) -> None:
    result = await _task_clean_expired_data({"days": 0})
    assert result["status"] == "skipped"


async def test_clean_expired_data_reads_retention_setting(db, client, admin_headers) -> None:
    """未显式传 days 时读 system_settings.data_retention_days。"""
    response = await client.put(
        "/api/system/settings/data_retention_days", headers=admin_headers, json={"value": 45}
    )
    assert response.status_code == 200, response.text

    result = await _task_clean_expired_data({})
    assert result["days"] == 45


async def test_backup_prunes_old_snapshots(db, client, monkeypatch, tmp_path) -> None:
    """定时备份必须按保留份数轮转，避免 backups/ 无上限增长。"""
    from app.services import backup as backup_module

    folder = tmp_path / "backups"
    folder.mkdir()
    for index in range(6):
        _stamp(folder / f"qbot-2026010{index + 1}-000000.db", index)

    async def fake_backup() -> str:
        # _stamp 建文件并设置 mtime，模拟"刚生成的最新快照"
        return _stamp(folder / "qbot-20260107-000000.db", 100)

    monkeypatch.setattr(backup_module, "_backup_dir", lambda: folder)
    monkeypatch.setattr(backup_module, "backup_database", fake_backup)

    result = await _task_backup({"keep": 3})
    assert result["keep"] == 3
    assert result["pruned"] >= 4
    assert len(list(folder.glob("qbot-*"))) == 3


async def test_backup_keep_falls_back_on_bad_value(db, client, monkeypatch, tmp_path) -> None:
    from app.services import backup as backup_module

    folder = tmp_path / "backups"
    folder.mkdir()

    async def fake_backup():
        target = folder / "qbot-x.db"
        target.write_bytes(b"x")
        return target

    monkeypatch.setattr(backup_module, "_backup_dir", lambda: folder)
    monkeypatch.setattr(backup_module, "backup_database", fake_backup)

    result = await _task_backup({"keep": "not-a-number"})
    assert result["keep"] == 14


async def test_setting_store_tolerates_bare_values(db, client) -> None:
    """历史/人工改库可能写入裸值，读取必须兼容而不是抛 AttributeError。"""
    from app.models import SystemSetting
    from app.services.settings_store import read_setting, setting_value

    db.add(SystemSetting(key="bare_value_probe", value=7))
    await db.commit()

    assert setting_value(SystemSetting(key="x", value=7)) == 7
    assert setting_value(SystemSetting(key="x", value={"value": 7})) == 7
    assert setting_value(None, "fallback") == "fallback"
    assert await read_setting(db, "bare_value_probe", 0) == 7
    assert await read_setting(db, "missing_key", "fallback") == "fallback"
