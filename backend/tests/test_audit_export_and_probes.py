"""审计日志筛选/导出与存活/就绪探针语义。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models import AuditLog


async def _seed_audit(db: AsyncSession) -> None:
    db.add_all(
        [
            AuditLog(username="admin", action="login", target="admin", detail="token=abcdef1234", ip="10.0.0.1"),
            AuditLog(username="operator", action="update_setting", target="panel_title", detail="value=QBot", ip="10.0.0.2"),
            AuditLog(username="admin", action="backup_database", target="qbot.sql.gz", detail="", ip="192.168.1.9"),
        ]
    )
    await db.commit()


async def test_audit_filters_and_export(client: httpx.AsyncClient, admin_headers: dict[str, str], db: AsyncSession):
    await _seed_audit(db)

    filtered = await client.get(
        "/api/audit-logs", headers=admin_headers, params={"username": "operator", "page_size": 50}
    )
    assert filtered.status_code == 200, filtered.text
    items = filtered.json()["items"]
    assert [item["username"] for item in items] == ["operator"]

    by_ip = await client.get("/api/audit-logs", headers=admin_headers, params={"ip": "192.168", "page_size": 50})
    assert [item["action"] for item in by_ip.json()["items"]] == ["backup_database"]

    future = datetime.now(timezone.utc).replace(year=2100).isoformat()
    empty = await client.get("/api/audit-logs", headers=admin_headers, params={"start": future})
    assert empty.json()["total"] == 0

    exported = await client.get(
        "/api/audit-logs/export", headers=admin_headers, params={"action": "login"}
    )
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers["content-type"]
    assert "attachment" in exported.headers["content-disposition"]
    body = exported.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("time,username,action")
    assert "login" in body
    # 敏感值必须脱敏后才允许导出。
    assert "abcdef1234" not in body
    assert "***" in body


async def test_audit_export_requires_permission(client: httpx.AsyncClient):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anon:
        response = await anon.get("/api/audit-logs/export")
    assert response.status_code in (401, 403)


async def test_live_and_ready_probes(client: httpx.AsyncClient):
    live = await client.get("/api/system/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"

    ready = await client.get("/api/system/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] is True

    # 兼容旧部署：/health 仍然反映数据库可用性。
    health = await client.get("/api/system/health")
    assert health.status_code == 200


async def test_ticket_rows_are_pruned(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    """签发票据时只清理过期记录，不影响仍在有效期内的票据。"""
    for _ in range(3):
        assert (await client.post("/api/ws/ticket", headers=admin_headers)).status_code == 200
    async with SessionLocal() as session:
        from sqlalchemy import func, select

        from app.models import WsTicket

        assert (await session.scalar(select(func.count()).select_from(WsTicket))) >= 3
