"""Push destinations must use the selected account's registered route IDs."""

from __future__ import annotations

import uuid

from app.models import Account, GithubRepository, Group, PushRule


async def test_rule_creation_and_retargeting_require_account_group_mapping(client, admin_headers, mock_account, db):
    suffix = uuid.uuid4().hex
    repo = GithubRepository(owner="push-boundary", name=suffix, full_name=f"push-boundary/{suffix}",
                            html_url=f"https://github.com/push-boundary/{suffix}")
    other = Account(account_id=f"push-target-{suffix}", name="target isolation", enabled=False)
    db.add_all([repo, other])
    await db.flush()
    db.add(Group(account_id=other.id, group_number=466001, name="only second account"))
    await db.commit()
    try:
        wrong_account = await client.post("/api/github/push-rules", headers=admin_headers, json={
            "repository_id": repo.id, "account_id": mock_account["id"], "qq_group": 466001,
        })
        assert wrong_account.status_code == 422, wrong_account.text
        created = await client.post("/api/github/push-rules", headers=admin_headers, json={
            "repository_id": repo.id, "account_id": mock_account["id"], "qq_group": 900001,
        })
        assert created.status_code == 201, created.text
        rule_id = created.json()["id"]
        for change in ({"qq_group": 466001}, {"account_id": other.id}):
            changed = await client.put(f"/api/github/push-rules/{rule_id}", headers=admin_headers, json=change)
            assert changed.status_code == 422, changed.text
        changed = await client.put(f"/api/github/push-rules/{rule_id}", headers=admin_headers,
                                   json={"account_id": other.id, "qq_group": 466001})
        assert changed.status_code == 200, changed.text
        assert changed.json()["account_id"] == other.id and changed.json()["qq_group"] == 466001
    finally:
        await db.delete(repo)
        await db.delete(other)
        await db.commit()


async def test_rule_update_rejects_null_fields_but_template_can_be_cleared(client, admin_headers, mock_account, db):
    suffix = uuid.uuid4().hex
    repo = GithubRepository(owner="push-boundary", name=suffix, full_name=f"push-boundary/{suffix}",
                            html_url=f"https://github.com/push-boundary/{suffix}")
    db.add(repo)
    await db.flush()
    rule = PushRule(repository_id=repo.id, account_id=mock_account["id"], qq_group=900001, template="custom template")
    db.add(rule)
    await db.commit()
    try:
        for field in ("enabled", "account_id", "qq_group", "mention_user_ids"):
            response = await client.put(f"/api/github/push-rules/{rule.id}", headers=admin_headers, json={field: None})
            assert response.status_code == 422, response.text
        cleared = await client.put(f"/api/github/push-rules/{rule.id}", headers=admin_headers, json={"template": None})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["template"] is None
        await db.refresh(rule)
        assert rule.enabled and rule.account_id == mock_account["id"] and rule.qq_group == 900001
        assert rule.mention_user_ids == []
    finally:
        await db.delete(repo)
        await db.commit()
