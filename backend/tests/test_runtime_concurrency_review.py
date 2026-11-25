"""Independent behavioral checks for claim fencing and expired inbox recovery."""

from datetime import datetime, timedelta, timezone
import time

from sqlalchemy import update

from app.models.account import QQEventInbox
from app.services import qq_inbox
from app.services.account_manager import AccountManager, RuntimeState
from tests.fakes import FakeOfficialAdapter


async def _accepted(account_id, suffix):
    inbox_id, _ = await qq_inbox.accept(account_id, {
        "op": 0, "t": "C2C_MESSAGE_CREATE", "id": f"review-{suffix}",
        "d": {"id": f"review-msg-{suffix}", "content": "claim review"},
    })
    token = await qq_inbox.claim(inbox_id)
    assert token
    return inbox_id, token


async def test_expired_inbox_claim_cannot_record_success(client, db, mock_account):
    inbox_id, token = await _accepted(mock_account["id"], "expired")
    await db.execute(update(QQEventInbox).where(QQEventInbox.id == inbox_id).values(
        lease_until=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    await db.commit()
    await qq_inbox.finish(inbox_id, token)
    row = await db.get(QQEventInbox, inbox_id, populate_existing=True)
    assert row.status != "success", "Expired ownership cannot attest successful processing"


async def test_exhausted_interrupted_inbox_is_dead_instead_of_blocking_recovery(client, db, mock_account):
    inbox_id, _ = await _accepted(mock_account["id"], "exhausted")
    await db.execute(update(QQEventInbox).where(QQEventInbox.id == inbox_id).values(
        attempts=qq_inbox.MAX_ATTEMPTS, lease_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        side_effect_started=False,
    ))
    await db.commit()
    assert await qq_inbox.claim(inbox_id) is None
    row = await db.get(QQEventInbox, inbox_id, populate_existing=True)
    assert row.status == "dead", "Exhausted expired entries must leave the recoverable batch"
    assert inbox_id not in {item[0] for item in await qq_inbox.pending(mock_account["id"])}


async def test_old_inbox_finisher_cannot_overwrite_a_new_claim(client, db, mock_account, monkeypatch):
    inbox_id, old_token = await _accepted(mock_account["id"], "fenced-finish")
    sessions = qq_inbox.SessionLocal
    swapped = False

    async def take_over():
        nonlocal swapped
        if swapped:
            return
        swapped = True
        async with sessions() as competing:
            await competing.execute(update(QQEventInbox).where(QQEventInbox.id == inbox_id).values(
                claim_id="new-claim-holder", status="processing",
                lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
            ))
            await competing.commit()

    class DelayedWriteSession:
        def __init__(self):
            self.inner = sessions()

        async def __aenter__(self):
            await self.inner.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.inner.__aexit__(*args)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        async def scalar(self, statement, *args, **kwargs):
            result = await self.inner.scalar(statement, *args, **kwargs)
            await take_over()
            return result

        async def execute(self, statement, *args, **kwargs):
            await take_over()
            return await self.inner.execute(statement, *args, **kwargs)

    monkeypatch.setattr(qq_inbox, "SessionLocal", DelayedWriteSession)
    await qq_inbox.finish(inbox_id, old_token)
    row = await db.get(QQEventInbox, inbox_id, populate_existing=True)
    assert swapped
    assert row.claim_id == "new-claim-holder" and row.status == "processing", "Old completion overwrote a newer claim"


async def test_expired_account_lease_never_reports_online():
    adapter = FakeOfficialAdapter()
    await adapter.connect()
    manager = AccountManager()
    manager._runtimes[1] = RuntimeState(
        account_db_id=1, account_uid="expired-review", name="expired", adapter=adapter,
        state="online", lease_id="expired-token", lease_valid_until=time.monotonic() - 1,
    )
    try:
        assert manager.adapter(1) is None
        assert not manager.is_online(1), "Online status must use the same ownership fence as sending"
    finally:
        await adapter.disconnect()
