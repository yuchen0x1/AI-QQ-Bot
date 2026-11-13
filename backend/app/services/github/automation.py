"""Persistent all-repository subscriptions and one-time QQ group binding."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models import Account, GithubNotificationTarget, GithubRepository, Group, PushRecord, PushRule, SystemSetting, User
from app.services.github.activity import EVENT_LABELS, sync_activity
from app.services.github.client import GithubClient
from app.services.github.monitor import import_repository_releases
from app.services.github.oauth import OAuthError, get_user_token, list_user_repos
from app.services.github.registry import create_monitored_repo

CONFIG_PREFIX = "github_notifications:"
BIND_PREFIX = "github_group_bind:"
PROBE_PREFIX = "github_delivery_probe:"
PERMISSION_PREFIX = "github_group_permission:"


def proactive_denied(error: str | None) -> bool:
    return "40034105" in (error or "")


async def save_delivery_probe(db: AsyncSession, target: GithubNotificationTarget, *, ok: bool, error: str = "") -> None:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == f"{PROBE_PREFIX}{target.id}"))
    value = {"user_id": target.user_id, "ok": ok, "error": error[:600], "at": datetime.now(timezone.utc).isoformat(),
             "account_id": target.account_id, "qq_group": target.qq_group, "mode": "proactive"}
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=f"{PROBE_PREFIX}{target.id}", value=value, description="通知群主动投递实测结果"))
    await db.commit()


async def save_group_permission(db: AsyncSession, target: GithubNotificationTarget, *, allowed: bool | None,
                                error: str = "") -> None:
    key = f"{PERMISSION_PREFIX}{target.id}"
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    value = {"user_id": target.user_id, "account_id": target.account_id, "qq_group": target.qq_group,
             "allowed": allowed, "error": error[:600], "at": datetime.now(timezone.utc).isoformat()}
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value, description="QQ 官方通知群主动消息权限检查"))
    await db.commit()


async def delivery_diagnostics(db: AsyncSession, user_id: int, targets: list[GithubNotificationTarget]) -> dict[int, dict]:
    def utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    minimum = datetime.min.replace(tzinfo=timezone.utc)
    state = {t.id: {"delivered": 0, "failed": 0, "pending": 0, "last_error": None, "error_at": minimum,
                    "permission_at": minimum, "success_at": minimum, "proactive_blocked": False} for t in targets}
    if not state:
        return state
    rows = await db.execute(select(PushRecord, PushRule.notification_target_id).join(PushRule, PushRule.id == PushRecord.rule_id)
                            .where(PushRule.managed_by_user_id == user_id, PushRule.notification_target_id.in_(state),
                                   PushRecord.created_at >= datetime.now(timezone.utc) - timedelta(days=7))
                            .order_by(PushRecord.id.desc()).limit(1000))
    for record, target_id in rows:
        item = state[target_id]
        if record.status == "success":
            item["delivered"] += 1
            item["success_at"] = max(item["success_at"], utc(record.sent_at or record.updated_at))
        elif record.status == "failed":
            item["failed"] += 1
            stamp = utc(record.updated_at)
            if stamp > item["error_at"]:
                item.update(last_error=record.error, error_at=stamp)
            if proactive_denied(record.error):
                item["permission_at"] = max(item["permission_at"], stamp)
        elif record.status in {"pending", "retrying"}:
            item["pending"] += 1
    probes = list(await db.scalars(select(SystemSetting).where(SystemSetting.key.in_([f"{PROBE_PREFIX}{target.id}" for target in targets]))))
    target_map = {t.id: t for t in targets}
    for row in probes:
        target_id = int(row.key.removeprefix(PROBE_PREFIX))
        probe, target = row.value or {}, target_map[target_id]
        if probe.get("account_id") != target.account_id or probe.get("qq_group") != target.qq_group:
            continue
        stamp = datetime.fromisoformat(probe["at"])
        item = state[target_id]
        item["last_probe_at"] = probe["at"]
        item["probe_ok"] = bool(probe.get("ok"))
        if probe.get("ok"):
            item["success_at"] = max(item["success_at"], stamp)
        else:
            if stamp > item["error_at"]:
                item.update(last_error=probe.get("error"), error_at=stamp)
            if proactive_denied(probe.get("error")):
                item["permission_at"] = max(item["permission_at"], stamp)
    for item in state.values():
        item["proactive_blocked"] = item["permission_at"] > item["success_at"]
        for key in ("permission_at", "success_at", "error_at"):
            item.pop(key)
    permissions = list(await db.scalars(select(SystemSetting).where(
        SystemSetting.key.in_([f"{PERMISSION_PREFIX}{target.id}" for target in targets]))))
    for row in permissions:
        target_id = int(row.key.removeprefix(PERMISSION_PREFIX))
        permission, target = row.value or {}, target_map[target_id]
        if permission.get("account_id") != target.account_id or permission.get("qq_group") != target.qq_group:
            continue
        item = state[target_id]
        item.update(allow_proactive_msg=permission.get("allowed"), permission_checked_at=permission.get("at"),
                    permission_error=permission.get("error") or None)
        if permission.get("allowed") is False:
            item["proactive_blocked"] = True
    return state


async def config_row(db: AsyncSession, user_id: int) -> SystemSetting | None:
    return await db.scalar(select(SystemSetting).where(SystemSetting.key == f"{CONFIG_PREFIX}{user_id}").execution_options(populate_existing=True))


async def read_config(db: AsyncSession, user_id: int) -> dict:
    row = await config_row(db, user_id)
    return dict(row.value) if row and isinstance(row.value, dict) else {}


async def save_config(db: AsyncSession, user_id: int, value: dict) -> None:
    row = await config_row(db, user_id)
    if row:
        row.value = dict(value)
    else:
        db.add(SystemSetting(key=f"{CONFIG_PREFIX}{user_id}", value=dict(value), description="全部 GitHub 仓库的群通知设置"))
    await db.commit()


async def list_targets(db: AsyncSession, user_id: int) -> list[GithubNotificationTarget]:
    return list(await db.scalars(select(GithubNotificationTarget).where(GithubNotificationTarget.user_id == user_id,
                                 GithubNotificationTarget.account_id.in_(select(Account.id).where(Account.protocol == "qq_official")))
                                 .order_by(GithubNotificationTarget.id).execution_options(populate_existing=True)))


async def get_target(db: AsyncSession, user_id: int, target_id: int | None = None) -> GithubNotificationTarget:
    query = select(GithubNotificationTarget).where(GithubNotificationTarget.user_id == user_id)
    if target_id is not None:
        query = query.where(GithubNotificationTarget.id == target_id)
    target = await db.scalar(query.order_by(GithubNotificationTarget.id).execution_options(populate_existing=True))
    if not target:
        raise OAuthError("通知群不存在，请先添加通知群")
    return target


async def annotate_group(db: AsyncSession, account_id: int, internal_id: int, number: str) -> None:
    group = await db.scalar(select(Group).where(Group.account_id == account_id, Group.group_number == internal_id))
    if not group:
        group = Group(account_id=account_id, group_number=internal_id)
        db.add(group)
    if number.isdigit():
        group.display_number = number


async def mirror_primary_target(db: AsyncSession, user_id: int) -> None:
    """Maintain the old single-group fields for older clients and rollback compatibility."""
    targets = await list_targets(db, user_id)
    value = await read_config(db, user_id)
    first = targets[0] if targets else None
    value.update(account_id=first.account_id if first else None, group_label=first.group_label if first else "",
                 qq_group=first.qq_group if first else None, revision=secrets.token_hex(12), sync_requested=True)
    await save_config(db, user_id, value)


async def reconcile_rules(db: AsyncSession, user_id: int, repo_ids: list[int] | None = None) -> None:
    """Give every enabled destination its own durable rule; never move another group's rule."""
    value = await read_config(db, user_id)
    targets = {t.id: t for t in await list_targets(db, user_id)}
    repos = {r.id: r for r in await db.scalars(select(GithubRepository).where(GithubRepository.owner_user_id == user_id))}
    rules = list(await db.scalars(select(PushRule).where(PushRule.managed_by_user_id == user_id).execution_options(populate_existing=True)))
    existing = set()
    for rule in rules:
        target = targets.get(rule.notification_target_id)
        repo = repos.get(rule.repository_id)
        rule.enabled = bool(value.get("enabled") and target and target.enabled and target.qq_group and repo and repo.monitor_enabled and repo.remote_available)
        rule.event_types = value.get("event_types") or ["release"]
        if target and target.qq_group:
            rule.account_id, rule.qq_group = target.account_id, target.qq_group
        existing.add((rule.repository_id, rule.notification_target_id))
    await db.flush()
    if value.get("enabled"):
        for repo in repos.values():
            if not repo.monitor_activity or not repo.monitor_enabled or not repo.remote_available or (repo_ids is not None and repo.id not in repo_ids):
                continue
            for target in targets.values():
                if not target.enabled or not target.qq_group or (repo.id, target.id) in existing:
                    continue
                try:
                    async with db.begin_nested():
                        db.add(PushRule(repository_id=repo.id, account_id=target.account_id, qq_group=target.qq_group,
                                        managed_by_user_id=user_id, notification_target_id=target.id,
                                        event_types=value.get("event_types") or ["release"], enabled=True, only_stable=False, ai_summary=False))
                        await db.flush()
                except IntegrityError:
                    pass  # A concurrent binding/sync already attached this destination.
    await db.commit()


def public_https_url() -> str:
    base = settings.public_base_url.rstrip("/")
    parsed = urlparse(base)
    host = parsed.hostname or ""
    invalid = parsed.scheme != "https" or not host or "." not in host or host.lower() == "localhost" or parsed.username or parsed.password or parsed.query or parsed.fragment
    try:
        invalid = invalid or not ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if invalid:
        raise OAuthError("实时 Webhook 需要先在服务器配置公网 HTTPS 的 PUBLIC_BASE_URL；本地可先使用轮询")
    return base


async def subscription_status(db: AsyncSession, user_id: int) -> dict:
    from app.services.scheduler import scheduler_service
    from app.services.account_manager import account_manager

    value = await read_config(db, user_id)
    token = await get_user_token(db, user_id)
    targets = await list_targets(db, user_id)
    accounts = {a.id: a for a in await db.scalars(select(Account))}
    delivery = await delivery_diagnostics(db, user_id, targets)
    warnings = []
    if not token:
        warnings.append("请先连接 GitHub Token")
    if not any(t.qq_group and t.enabled for t in targets):
        warnings.append("尚无已启用且绑定成功的通知群，请添加通知群并完成绑定")
    if not scheduler_service.running:
        warnings.append("后台调度未运行，自动同步与轮询暂停")
    for account_id in {t.account_id for t in targets if t.enabled}:
        account = accounts.get(account_id)
        if not account or not account_manager.is_online(account_id):
            warnings.append(f"发送机器人 {account.name if account else account_id} 尚未在线")
        if account and account.connection_mode == "official_webhook" and settings.public_base_url.startswith(("http://127.0.0.1", "http://localhost")):
            warnings.append(f"{account.name} 使用 Webhook；本地运行需公网回调，或将 QQ 平台与后台均切换为 WebSocket")
    for target in targets:
        if target.enabled and delivery[target.id]["proactive_blocked"]:
            warnings.append(f"群 {target.group_label} 主动推送受限，请在 QQ 群内开启机器人的「允许主动发送」，然后检查群权限并测试通知")
    if targets:
        value.update(account_id=targets[0].account_id, group_label=targets[0].group_label, qq_group=targets[0].qq_group)
    return {**value, "group_bound": any(t.qq_group and t.enabled for t in targets),
            "targets": [{"id": t.id, "account_id": t.account_id, "account_name": accounts[t.account_id].name if t.account_id in accounts else "账号已删除",
                         "protocol": accounts[t.account_id].protocol if t.account_id in accounts else "", "group_label": t.group_label,
                         "qq_group": t.qq_group, "enabled": t.enabled, "bound": bool(t.qq_group), "updated_at": t.updated_at.isoformat(),
                         "delivery": delivery[t.id]} for t in targets],
            "delivery_blocked": any(delivery[t.id]["proactive_blocked"] for t in targets if t.enabled),
            "failed_deliveries": sum(item["failed"] for item in delivery.values()),
            "bound_target_count": sum(bool(t.qq_group and t.enabled) for t in targets),
            "scheduler_running": scheduler_service.running, "connected": token is not None, "warnings": warnings,
            "event_options": [{"value": key, "label": label} for key, label in EVENT_LABELS.items()]}


async def make_binding_code(db: AsyncSession, user_id: int, target_id: int | None = None) -> dict:
    target = await get_target(db, user_id, target_id)
    code = secrets.token_urlsafe(18)
    # Remove earlier codes for this user. Only the hash of the fresh code is stored.
    rows = list(await db.scalars(select(SystemSetting).where(SystemSetting.key.startswith(BIND_PREFIX))))
    for row in rows:
        if (row.value or {}).get("user_id") == user_id and (row.value or {}).get("target_id") in {None, target.id}:
            await db.delete(row)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.add(SystemSetting(key=BIND_PREFIX + hashlib.sha256(code.encode()).hexdigest(), value={
        "user_id": user_id, "target_id": target.id, "account_id": target.account_id, "group_label": target.group_label, "expires_at": expires.isoformat(),
    }, description="一次性通知群绑定（10 分钟有效）", is_secret=True))
    await db.commit()
    return {"command": f"/绑定通知群 {code}", "expires_at": expires.isoformat(), "group_label": target.group_label, "target_id": target.id}


async def bind_from_message(db: AsyncSession, account_id: int, group_id: int, text: str) -> str | None:
    if not text.startswith("/绑定通知群"):
        return None
    code = text.removeprefix("/绑定通知群").strip()
    key = BIND_PREFIX + hashlib.sha256(code.encode()).hexdigest()
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if not row or not isinstance(row.value, dict):
        return "绑定口令无效或已使用，请在仓库通知页重新生成。"
    data = row.value
    if data.get("account_id") != account_id or datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
        return "绑定口令已过期或不属于当前机器人，请重新生成。"
    try:
        target = await get_target(db, data["user_id"], data.get("target_id"))
    except OAuthError:
        return "通知群已移除，请重新添加并生成口令。"
    if target.account_id != account_id or target.group_label != data.get("group_label"):
        return "通知设置已改变，请重新生成绑定口令。"
    duplicate = await db.scalar(select(GithubNotificationTarget.id).where(GithubNotificationTarget.user_id == data["user_id"],
                                 GithubNotificationTarget.account_id == account_id, GithubNotificationTarget.qq_group == group_id,
                                 GithubNotificationTarget.id != target.id))
    if duplicate:
        return "当前群已绑定到另一个通知目标，请核对填写的群号。"
    # Claim the code before applying the mapping. Concurrent replays cannot bind another group.
    claimed = await db.execute(delete(SystemSetting).where(SystemSetting.id == row.id))
    if not claimed.rowcount:
        await db.rollback()
        return "绑定口令已使用。"
    target.qq_group = group_id
    target.updated_at = datetime.now(timezone.utc)
    await annotate_group(db, account_id, group_id, target.group_label)
    await db.commit()
    await mirror_primary_target(db, data["user_id"])
    await reconcile_rules(db, data["user_id"])
    return f"已将当前群绑定为通知群 {target.group_label}。请由群主或管理员在 QQ 群内开启本机器人的「允许主动发送／主动推送」，然后在后台检查群权限并测试主动通知；左侧「新手指引与文档」有完整步骤。"


async def sync_subscription(db: AsyncSession, user_id: int) -> None:
    value = await read_config(db, user_id)
    if not value.get("enabled"):
        return
    requested = bool(value.get("sync_requested"))
    connected = await get_user_token(db, user_id)
    if not connected or not decrypt_secret(connected.access_token_enc):
        value.update(sync_status="waiting", sync_requested=False, last_error=None)
        await save_config(db, user_id, value)
        return
    last = value.get("last_sync_started_at") or value.get("last_sync_at")
    if not value.get("sync_requested") and last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 55:
        return
    value.update(sync_status="running", sync_requested=False, last_sync_started_at=datetime.now(timezone.utc).isoformat())
    await save_config(db, user_id, value)
    imported, monitored, failed = [], [], []
    effective_interval = value["poll_interval_seconds"]
    try:
        user = await db.get(User, user_id)
        row = await get_user_token(db, user_id)
        token = decrypt_secret(row.access_token_enc) if row else None
        if not user or not user.is_active or not row or not token:
            raise OAuthError("请先连接有效的 GitHub Token")
        base = public_https_url() if value.get("install_webhooks") else None
        client = GithubClient(token)
        items = []
        for page in range(1, 51):
            batch = await list_user_repos(token, page=page)
            items.extend(item for item in batch if item["owner"].lower() == row.login.lower())
            if len(batch) < 100:
                break
        else:
            raise OAuthError("仓库分页超过 5000 个上限，请缩小授权范围或分批配置")
        # Reconcile only after a complete, successful listing. A timeout/403 must never hide repositories.
        visible = {item["full_name"].lower() for item in items}
        if (await read_config(db, user_id)).get("revision") != value.get("revision"):
            raise OAuthError("通知设置已更新，等待按最新配置重新同步")
        existing = list(await db.scalars(select(GithubRepository).where(
            GithubRepository.owner_user_id == user_id, GithubRepository.provider == "github",
            GithubRepository.monitor_activity.is_(True))))
        from app.services.scheduler import scheduler_service

        for repo in existing:
            if repo.owner.lower() != row.login.lower():
                continue
            repo.remote_available = repo.full_name.lower() in visible
            if not repo.remote_available:
                repo.last_check_status = "unavailable"
                repo.last_check_error = "GitHub 完整仓库列表中已不可见：可能已删除、转移或收回 Token 访问权限，历史记录保留"
                scheduler_service.unschedule_repo(repo.id)
        await db.commit()
        await reconcile_rules(db, user_id)
        effective_interval = max(value["poll_interval_seconds"], math.ceil(len(items) * 3 * 3600 / 3000))
        for item in items:
            full_name = item["full_name"]
            try:
                repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name.ilike(full_name)))
                if repo and repo.owner_user_id != user_id:
                    failed.append({"repository": full_name, "error": "仓库已由其他用户或全局配置管理，未覆盖"})
                    continue
                if not repo:
                    repo, _ = await create_monitored_repo(db, provider="github", owner=item["owner"], name=item["name"], token=token,
                                                         monitor_enabled=False, owner_user_id=user_id, persist_token=False,
                                                         poll_interval_seconds=value["poll_interval_seconds"], notify_prerelease=True)
                    imported.append(full_name)
                if repo.activity_initialized_at is None:
                    # Baseline first, attach rules second: importing never broadcasts history.
                    await import_repository_releases(db, repo, client)
                    await sync_activity(db, repo, client, notify=False)
                current_config = await read_config(db, user_id)
                if current_config.get("revision") != value.get("revision"):
                    raise OAuthError("通知设置已更新，等待按最新配置重新同步")
                repo.monitor_activity = True
                repo.remote_available = True
                repo.monitor_enabled = True
                for field in ("description", "language", "stars", "html_url"):
                    if item.get(field) is not None:
                        setattr(repo, field, item[field])
                previous_interval = repo.poll_interval_seconds
                repo.poll_interval_seconds = max(effective_interval, client.poll_interval)
                await db.commit()
                await reconcile_rules(db, user_id, [repo.id])
                scheduler_service.schedule_repo_poll(repo, replace=previous_interval != repo.poll_interval_seconds)
                monitored.append(full_name)
                if base and (requested or full_name in imported):
                    if not repo.webhook_secret_enc:
                        repo.webhook_secret_enc = encrypt_secret(secrets.token_urlsafe(32))
                        await db.commit()
                    await client.ensure_webhook(repo.owner, repo.name, url=f"{base}/api/webhook/github/{repo.id}",
                                                secret=decrypt_secret(repo.webhook_secret_enc) or "", events=list(set(value["event_types"]) | {"repository"}))
            except Exception as exc:  # noqa: BLE001 — report each failed repository
                await db.rollback()
                failed.append({"repository": full_name, "error": str(exc)[:240]})
                if getattr(exc, "rate_limited", False):
                    failed.append({"repository": "剩余仓库", "error": "GitHub 限流，等待下一次自动同步"})
                    break
        state = "partial" if failed else "ok"
        error = None
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        state, error = "error", str(exc)[:300]
    # Re-read so a concurrent edit or group-binding operation is never overwritten.
    config = await config_row(db, user_id)
    if config:
        await db.refresh(config)
        current = dict(config.value)
        current.update(last_sync_at=datetime.now(timezone.utc).isoformat(), sync_status=state, last_error=error,
                       imported_count=len(imported), monitored_count=len(monitored), failures=failed[:50],
                       effective_poll_interval_seconds=effective_interval)
        await save_config(db, user_id, current)
        if state in {"error", "partial"}:
            from app.services.logs import write_log
            await write_log(db, level="ERROR", category="github",
                            message=f"GitHub 仓库同步异常：{error or str(failed[:3])[:400]}")


async def tick_subscriptions() -> None:
    from app.db.session import SessionLocal
    from app.services.github.notify import retry_failed_pushes

    async with SessionLocal() as db:
        rows = list(await db.scalars(select(SystemSetting).where(SystemSetting.key.startswith(CONFIG_PREFIX))))
        for row in rows:
            await sync_subscription(db, int(row.key.removeprefix(CONFIG_PREFIX)))
        await retry_failed_pushes(db)
