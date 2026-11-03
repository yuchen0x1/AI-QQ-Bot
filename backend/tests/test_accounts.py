"""多账号：创建、启停、能力检测、群同步、数据隔离。"""

from __future__ import annotations

import asyncio

import httpx

from app.services.account_manager import account_manager


async def test_onebot_requires_api_base(client: httpx.AsyncClient, admin_headers: dict[str, str]):
    resp = await client.post(
        "/api/accounts", headers=admin_headers, json={"name": "缺少地址的账号", "protocol": "onebot11"}
    )
    assert resp.status_code == 400
    assert "HTTP API 地址" in resp.json()["detail"]


async def test_create_start_stop(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict):
    listing = await client.get("/api/accounts", headers=admin_headers)
    assert listing.status_code == 200
    account = next(a for a in listing.json() if a["id"] == mock_account["id"])
    assert account["runtime_state"] == "online"
    assert account["connection"]["status"] == "online"
    assert account["online_seconds"] >= 0
    assert account["capabilities"]["set_group_ban"] is True

    caps = await client.get(f"/api/accounts/{mock_account['id']}/capabilities", headers=admin_headers)
    assert caps.status_code == 200
    assert any(item["key"] == "send_group_message" and item["supported"] for item in caps.json()["capabilities"])

    stopped = await client.post(f"/api/accounts/{mock_account['id']}/stop", headers=admin_headers)
    assert stopped.status_code == 200
    await asyncio.sleep(0.2)
    assert not account_manager.is_online(mock_account["id"])

    restarted = await client.post(f"/api/accounts/{mock_account['id']}/restart", headers=admin_headers)
    assert restarted.status_code == 200
    for _ in range(30):
        if account_manager.is_online(mock_account["id"]):
            break
        await asyncio.sleep(0.1)
    assert account_manager.is_online(mock_account["id"])


async def test_sync_groups_and_members(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict):
    sync = await client.post(f"/api/groups/sync/{mock_account['id']}", headers=admin_headers)
    assert sync.status_code == 200, sync.text
    groups = await client.get(f"/api/groups?account_id={mock_account['id']}", headers=admin_headers)
    assert groups.status_code == 200
    items = groups.json()["items"]
    assert len(items) >= 2
    group = items[0]

    members = await client.post(f"/api/groups/{group['id']}/sync", headers=admin_headers)
    assert members.status_code == 200, members.text
    member_list = await client.get(f"/api/groups/{group['id']}/members", headers=admin_headers)
    assert member_list.status_code == 200
    assert member_list.json()["total"] >= 1


async def test_group_action_permission_and_capability(
    client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict
):
    await client.post(f"/api/groups/sync/{mock_account['id']}", headers=admin_headers)
    groups = (await client.get(f"/api/groups?account_id={mock_account['id']}", headers=admin_headers)).json()["items"]
    group = groups[0]
    resp = await client.post(
        f"/api/groups/{group['id']}/action",
        headers=admin_headers,
        json={"action": "mute", "user_id": 20003, "duration_seconds": 60},
    )
    assert resp.status_code == 200, resp.text
    adapter = account_manager.adapter(mock_account["id"])
    assert adapter.bans[(group["group_number"], 20003)] == 60

    missing = await client.post(
        f"/api/groups/{group['id']}/action", headers=admin_headers, json={"action": "mute"}
    )
    assert missing.status_code == 400


async def test_multi_account_isolation(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict):
    second = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json={
            "name": "第二个模拟账号",
            "protocol": "mock",
            "connection_mode": "http",
            "qq_number": 200002,
            "auto_reconnect": False,
        },
    )
    assert second.status_code == 201
    account_b = second.json()
    assert (await client.post(f"/api/accounts/{account_b['id']}/start", headers=admin_headers)).status_code == 200
    for _ in range(30):
        if account_manager.is_online(account_b["id"]):
            break
        await asyncio.sleep(0.1)
    try:
        adapter_a = account_manager.adapter(mock_account["id"])
        adapter_b = account_manager.adapter(account_b["id"])
        assert adapter_a is not adapter_b

        sent = await client.post(
            "/api/messages/send",
            headers=admin_headers,
            json={"account_id": mock_account["id"], "qq_group": 900001, "content": "仅账号 A 发送"},
        )
        assert sent.status_code == 200, sent.text
        assert len(adapter_a.outbox) == 1
        assert adapter_a.outbox[0]["message"] == "仅账号 A 发送"
        assert len(adapter_b.outbox) == 0

        # 群配置隔离：修改 A 的群配置不影响 B 的相同群号
        await client.post(f"/api/groups/sync/{mock_account['id']}", headers=admin_headers)
        await client.post(f"/api/groups/sync/{account_b['id']}", headers=admin_headers)
        groups_a = (await client.get(f"/api/groups?account_id={mock_account['id']}", headers=admin_headers)).json()["items"]
        groups_b = (await client.get(f"/api/groups?account_id={account_b['id']}", headers=admin_headers)).json()["items"]
        assert {g["group_number"] for g in groups_a} == {g["group_number"] for g in groups_b}

        target = next(g for g in groups_a if g["group_number"] == 900001)
        updated = await client.put(
            f"/api/groups/{target['id']}/settings",
            headers=admin_headers,
            json={"moderation_mode": "strict", "ai_prompt": "账号A专属提示词"},
        )
        assert updated.status_code == 200
        other = next(g for g in groups_b if g["group_number"] == 900001)
        assert other["settings"]["moderation_mode"] != "strict"
        fetched = (await client.get(f"/api/groups/{other['id']}", headers=admin_headers)).json()
        assert fetched["settings"]["moderation_mode"] == "normal"
    finally:
        await client.delete(f"/api/accounts/{account_b['id']}", headers=admin_headers)


async def test_account_stats(client: httpx.AsyncClient, admin_headers: dict[str, str], mock_account: dict):
    stats = await client.get("/api/accounts/stats", headers=admin_headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] >= 1
    assert body["online"] >= 1
