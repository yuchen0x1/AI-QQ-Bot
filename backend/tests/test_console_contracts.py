"""Message directory and cursor contracts used by the existing console."""

from sqlalchemy import select

from app.models import Group, Message, QQOfficialIdentity


async def test_contact_directory_is_account_scoped_and_does_not_expose_openids(client, admin_headers, mock_account, db):
    account_id = mock_account["id"]
    user = QQOfficialIdentity(account_id=account_id, kind="user", scope="", openid="private-platform-secret", display_name="已登记联系人")
    member = QQOfficialIdentity(account_id=account_id, kind="member", scope="group-secret", openid="member-secret", display_name="只有群内身份")
    db.add_all([user, member])
    await db.commit()
    response = await client.get("/api/messages/contacts", headers=admin_headers, params={"account_id": account_id})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["id"] == user.id
    assert item["identifier_kind"] == "internal_mapping_id"
    assert "openid" not in item
    rejected = await client.post("/api/messages/send", headers=admin_headers, json={"account_id": account_id, "user_id": member.id, "content": "不能使用群成员身份私聊"})
    assert rejected.status_code == 422
    sent = await client.post("/api/messages/send", headers=admin_headers, json={"account_id": account_id, "user_id": user.id, "content": "使用已登记私聊身份"})
    assert sent.status_code == 200, sent.text


async def test_message_cursor_drains_all_batches_in_order(client, admin_headers, mock_account, db):
    account_id = mock_account["id"]
    messages = [Message(account_id=account_id, direction="in", message_type="private", sender_id=7, content=f"cursor-{index}") for index in range(205)]
    db.add_all(messages)
    await db.commit()
    cursor = min(message.id for message in messages) - 1
    first = await client.get("/api/messages", headers=admin_headers, params={"account_id": account_id, "after_id": cursor, "page_size": 200})
    assert first.status_code == 200
    ids = [item["id"] for item in first.json()["items"]]
    assert ids == sorted(ids)
    assert len(ids) == 200
    second = await client.get("/api/messages", headers=admin_headers, params={"account_id": account_id, "after_id": ids[-1], "page_size": 200})
    assert len(second.json()["items"]) == 5
    assert len(set(ids + [item["id"] for item in second.json()["items"]])) == 205


async def test_group_201_is_searchable_and_invalid_targets_never_send(client, admin_headers, mock_account, db):
    account_id = mock_account["id"]
    existing = set(await db.scalars(select(Group.group_number).where(Group.account_id == account_id)))
    db.add_all(Group(account_id=account_id, group_number=990000 + index, name=f"别名-{index}")
               for index in range(1, 202) if 990000 + index not in existing)
    await db.commit()
    response = await client.get("/api/groups", headers=admin_headers, params={"account_id": account_id, "keyword": "别名-201", "page_size": 50})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["group_number"] == 990201
    rejected = await client.post("/api/messages/send", headers=admin_headers, json={"account_id": account_id, "qq_group": 777777777, "content": "未登记目标"})
    assert rejected.status_code == 422
