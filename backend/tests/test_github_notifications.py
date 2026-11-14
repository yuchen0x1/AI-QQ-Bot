"""All-repository notifications: real API contracts with isolated mock transports."""

import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.core.http import set_transport
from app.core.security import decrypt_secret
from app.models import Account, GithubEvent, GithubRepository, PushRecord, PushRule, UserGithubToken
from app.services.account_manager import account_manager
from app.services.github.activity import sync_activity
from app.services.github.automation import bind_from_message, read_config, save_config, sync_subscription
from app.services.github.client import GithubClient
from app.services.github.notify import retry_failed_pushes

TOKEN = "github_pat_test_notifications_only"


def repo_payload(name, *, archived=False):
    owner, name = name.split("/", 1)
    return {"full_name": f"{owner}/{name}", "name": name, "owner": {"login": owner},
            "html_url": f"https://github.com/{owner}/{name}", "default_branch": "main", "archived": archived}


@pytest.fixture
def notification_transport():
    state = {"repos": ["notifier/project-one"], "events": [], "invalid": False, "hooks": [], "archived": set()}

    def handler(request):
        path = request.url.path
        if path == "/user":
            if state["invalid"]:
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(200, json={"id": 881122, "login": "notifier"})
        if path == "/user/repos":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[repo_payload(n, archived=n in state["archived"])
                                             for n in state["repos"][(page-1)*100:page*100]])
        if path.endswith("/events"):
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=state["events"][(page-1)*100:page*100], headers={"X-Poll-Interval": "60"})
        if path.endswith("/releases") or path.endswith("/tags"):
            return httpx.Response(200, json=[])
        if path.endswith("/hooks") and request.method == "GET":
            return httpx.Response(200, json=state["hooks"])
        if "/hooks" in path:
            state["hook_write"] = (request.method, json.loads(request.content))
            return httpx.Response(201, json={"id": 1})
        if path.startswith("/repos/") and len(path.split("/")) == 4:
            name = "/".join(path.split("/")[2:])
            return httpx.Response(200, json=repo_payload(name, archived=name in state["archived"]))
        return httpx.Response(404, json={"message": "Not Found"})

    set_transport(httpx.MockTransport(handler))
    yield state
    set_transport(None)


async def configure(client, headers, account):
    account_manager.adapter(account["id"]).groups[123456789] = {"group_id": 123456789, "group_name": "模拟通知群"}
    await account_manager.sync_groups(account["id"])
    connected = await client.post("/api/github/oauth/token", headers=headers, json={"token": TOKEN})
    assert connected.status_code == 200, connected.text
    result = await client.put("/api/github/automation", headers=headers,
                              json={"account_id": account["id"], "qq_group": 123456789})
    assert result.status_code == 200, result.text


async def test_token_connection_validates_and_never_echoes(client, admin_headers, db, notification_transport):
    response = await client.post("/api/github/oauth/token", headers=admin_headers, json={"token": TOKEN})
    assert response.status_code == 200
    assert response.json()["login"] == "notifier"
    assert TOKEN not in response.text
    row = await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))
    assert row.access_token_enc != TOKEN
    assert decrypt_secret(row.access_token_enc) == TOKEN
    notification_transport["invalid"] = True
    rejected = await client.post("/api/github/oauth/token", headers=admin_headers, json={"token": "invalid_token_for_test"})
    assert rejected.status_code == 400
    assert "invalid_token_for_test" not in rejected.text
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anonymous:
        unauthenticated = await anonymous.post("/api/github/oauth/token", json={"token": TOKEN})
    assert unauthenticated.status_code == 401


async def test_discovers_all_pages_then_new_repositories_without_history_spam(client, admin_headers, db, mock_account, notification_transport):
    await configure(client, admin_headers, mock_account)
    notification_transport["repos"] = ["notifier/project-one"] + [f"collaborator/skip-{n}" for n in range(99)] + ["notifier/project-two"]
    notification_transport["events"] = [{"id": "100", "type": "PushEvent", "actor": {"login": "notifier"},
                                         "payload": {"ref": "refs/heads/main", "before": "a"*40, "head": "b"*40,
                                                     "commits": [{"id": "b"*40, "message": "历史提交"}]}}]
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    config = await read_config(db, user_id)
    assert config["sync_status"] == "ok", config
    assert config["monitored_count"] == 2
    assert not account_manager.adapter(mock_account["id"]).outbox
    notification_transport["repos"].append("notifier/project-three")
    config["sync_requested"] = True
    await save_config(db, user_id, config)
    await sync_subscription(db, user_id)
    assert (await read_config(db, user_id))["monitored_count"] == 3
    rules = list(await db.scalars(select(PushRule).where(PushRule.managed_by_user_id == user_id, PushRule.account_id == mock_account["id"])))
    assert len(rules) == 3
    assert all("push" in r.event_types and r.qq_group == 123456789 for r in rules)


async def test_missing_repository_leaves_active_counts_and_can_return(client, admin_headers, db, mock_account, notification_transport):
    await configure(client, admin_headers, mock_account)
    notification_transport["repos"] = ["notifier/project-one", "notifier/project-two"]
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name == "notifier/project-two"))
    notification_transport["repos"] = ["notifier/project-one"]
    cfg = await read_config(db, user_id)
    cfg["sync_requested"] = True
    await save_config(db, user_id, cfg)
    await sync_subscription(db, user_id)
    await db.refresh(repo)
    assert repo.remote_available is False
    listed = (await client.get('/api/github/repos', headers=admin_headers)).json()
    assert repo.id not in {r["id"] for r in listed}
    history = (await client.get('/api/github/repos', params={"include_unavailable":True}, headers=admin_headers)).json()
    assert repo.id in {r["id"] for r in history}
    assert not await db.scalar(select(PushRule.id).where(PushRule.repository_id == repo.id, PushRule.enabled.is_(True)))
    notification_transport["repos"].append("notifier/project-two")
    cfg = await read_config(db, user_id)
    cfg["sync_requested"] = True
    await save_config(db, user_id, cfg)
    await sync_subscription(db, user_id)
    await db.refresh(repo)
    assert repo.remote_available is True


async def test_failed_repository_listing_does_not_hide_existing(client, admin_headers, db, mock_account, notification_transport, monkeypatch):
    from app.services.github import automation
    from app.services.github.oauth import OAuthError
    await configure(client, admin_headers, mock_account)
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name == "notifier/project-one"))
    async def fail(*args, **kwargs):
        raise OAuthError("GitHub timed out")
    monkeypatch.setattr(automation, "list_user_repos", fail)
    cfg = await read_config(db, user_id)
    cfg["sync_requested"] = True
    await save_config(db, user_id, cfg)
    await sync_subscription(db, user_id)
    await db.refresh(repo)
    assert repo.remote_available is True
    assert (await read_config(db, user_id))["sync_status"] == "error"


async def test_signed_push_and_comment_are_delivered_once_and_retry_after_offline(client, admin_headers, db, mock_account, notification_transport):
    await configure(client, admin_headers, mock_account)
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name == "notifier/project-one"))
    await client.put(f"/api/github/repos/{repo.id}", headers=admin_headers, json={"webhook_secret": "activity-secret"})
    push = {"ref": "refs/heads/main", "before": "1"*40, "after": "2"*40,
            "sender": {"login": "notifier"}, "commits": [{"id": "2"*40, "message": "修复登录问题"}],
            "repository": {"full_name": repo.full_name}}

    async def webhook(kind, payload, delivery):
        body = json.dumps(payload).encode()
        return await client.post(f"/api/webhook/github/{repo.id}", content=body,
                                 headers={"x-github-event": kind, "x-github-delivery": delivery,
                                          "x-hub-signature-256": "sha256="+hmac.new(b"activity-secret", body, hashlib.sha256).hexdigest()})

    first = await webhook("push", push, "push-1")
    records_at_failure = (await client.get("/api/github/push-records", headers=admin_headers)).json()
    assert first.status_code == 200 and first.json()["pushed"] == 1, (first.text, records_at_failure)
    repeated = await webhook("push", push, "push-1")
    assert repeated.json()["pushed"] == 0
    # Polling the same commit does not deliver it again.
    notification_transport["events"] = [{"id": "102", "type": "PushEvent", "actor": {"login": "notifier"},
                                         "payload": {**push, "head": push["after"]}}]
    repo.activity_initialized_at = datetime.now(timezone.utc)
    result = await sync_activity(db, repo, GithubClient(TOKEN), notify=True)
    assert result["pushed"] == 0
    comment = {"action": "created", "sender": {"login": "reviewer"}, "issue": {"number": 7},
               "comment": {"id": 7788, "body": "请补充复现步骤", "html_url": "https://github.com/notifier/project-one/issues/7#comment-7788"}}
    response = await webhook("issue_comment", comment, "comment-1")
    assert response.json()["pushed"] == 1
    assert len(account_manager.adapter(mock_account["id"]).outbox) == 2
    assert "修复登录问题" in account_manager.adapter(mock_account["id"]).outbox[0]["message"]
    # Re-delivery of the same body with a new delivery id is still suppressed.
    assert (await webhook("issue_comment", comment, "comment-2")).json()["pushed"] == 0
    records = (await client.get("/api/github/push-records", headers=admin_headers)).json()["items"]
    assert any(r["event_id"] and r["release_id"] is None for r in records)


async def test_one_time_group_binding_is_account_specific(client, admin_headers, db, mock_account, notification_transport):
    await configure(client, admin_headers, mock_account)
    response = await client.post("/api/github/automation/binding-code", headers=admin_headers)
    assert response.status_code == 200
    command = response.json()["command"]
    wrong = await bind_from_message(db, mock_account["id"]+999, 9001, command)
    assert "不属于" in wrong
    correct = await bind_from_message(db, mock_account["id"], 9001, command)
    assert "已将当前群绑定" in correct
    repeated = await bind_from_message(db, mock_account["id"], 9002, command)
    assert "无效" in repeated
    state = (await client.get("/api/github/automation", headers=admin_headers)).json()
    assert state["qq_group"] == 9001
    assert command not in json.dumps(state)


async def test_disabling_subscription_stops_failed_deliveries(client, admin_headers, db, mock_account, notification_transport):
    await configure(client, admin_headers, mock_account)
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    rule = await db.scalar(select(PushRule).where(PushRule.account_id == mock_account["id"], PushRule.managed_by_user_id == user_id))
    event = GithubEvent(repository_id=rule.repository_id, event_type="push", dedupe_key=f"retry-test:{rule.id}", source="webhook", payload={})
    db.add(event)
    await db.commit()
    record = PushRecord(repository_id=rule.repository_id, rule_id=rule.id, event_id=event.id, account_id=rule.account_id,
                        qq_group=rule.qq_group, content="旧的失败通知", status="failed")
    db.add(record)
    await db.commit()
    response = await client.put("/api/github/automation", headers=admin_headers,
                                json={"account_id": mock_account["id"], "qq_group": 123456789, "enabled": False})
    assert response.status_code == 200
    await retry_failed_pushes(db)
    await db.refresh(record)
    assert record.status == "cancelled"
    assert not account_manager.adapter(mock_account["id"]).outbox


async def test_offline_retry_preserves_the_real_failure(client, admin_headers, db, mock_account, notification_transport, monkeypatch):
    await configure(client, admin_headers, mock_account)
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    rule = await db.scalar(select(PushRule).where(PushRule.account_id == mock_account["id"],
                                                PushRule.managed_by_user_id == user_id, PushRule.enabled.is_(True)))
    assert rule is not None
    record = PushRecord(repository_id=rule.repository_id, rule_id=rule.id, account_id=rule.account_id,
                        qq_group=rule.qq_group, content="待重试更新", status="failed", retries=1,
                        error="40034105 主动消息失败，无权限")
    db.add(record)
    await db.commit()
    with monkeypatch.context() as patch:
        patch.setattr(account_manager, "is_online", lambda account_id: False)
        result = await retry_failed_pushes(db)
    await db.refresh(record)
    assert result["attempted"] == 0
    assert record.retries == 1 and record.status == "failed"
    assert record.error == "40034105 主动消息失败，无权限"


async def test_permission_check_and_proactive_probe_recover(client, admin_headers, db, mock_account, notification_transport, monkeypatch):
    from app.adapters.qq_official import QQOfficialApiError

    await configure(client, admin_headers, mock_account)
    account = await db.get(Account, mock_account["id"])
    account.protocol = "qq_official"
    await db.commit()
    adapter = account_manager.adapter(account.id)
    allowed = False

    async def permission(group_id):
        return {"allow_proactive_msg": allowed}

    async def proactive(group_id, content):
        if not allowed:
            raise QQOfficialApiError(40034105, "主动消息失败，无权限")
        return {"data": {"message_id": 12345}}

    monkeypatch.setattr(adapter, "protocol", "qq_official")
    monkeypatch.setattr(adapter, "get_group_bot_state", permission, raising=False)
    monkeypatch.setattr(adapter, "send_proactive_group_message", proactive, raising=False)
    state = (await client.get("/api/github/automation", headers=admin_headers)).json()
    target_id = next(t["id"] for t in state["targets"] if t["account_id"] == account.id)
    checked = await client.post(f"/api/github/automation/targets/{target_id}/permissions", headers=admin_headers)
    assert checked.status_code == 200 and checked.json()["delivery_blocked"]
    rejected = await client.post("/api/github/automation/test", params={"target_id": target_id}, headers=admin_headers)
    assert rejected.status_code == 400 and "40034105" in rejected.text
    allowed = True
    # A successful proactive test also replaces a stale disabled permission snapshot.
    recovered = await client.post("/api/github/automation/test", params={"target_id": target_id}, headers=admin_headers)
    assert recovered.status_code == 200, recovered.text
    state = (await client.get("/api/github/automation", headers=admin_headers)).json()
    target = next(t for t in state["targets"] if t["id"] == target_id)
    assert target["delivery"]["allow_proactive_msg"] is True
    assert not target["delivery"]["proactive_blocked"]
    assert not state["delivery_blocked"]


async def test_webhook_configuration_preserves_unrelated_hooks(notification_transport):
    notification_transport["hooks"] = [{"id": 987, "config": {"url": "https://other.example/webhook"}}]
    await GithubClient(TOKEN).ensure_webhook("notifier", "project-one", url="https://panel.example/api/webhook/github/1", secret="webhook-secret", events=["push", "issues"])
    method, payload = notification_transport["hook_write"]
    assert method == "POST"
    assert payload["events"] == ["push", "issues"]
    assert payload["config"]["insecure_ssl"] == "0"
    assert notification_transport["hooks"][0]["id"] == 987


async def two_targets(client, admin_headers, db, mock_account):
    await configure(client, admin_headers, mock_account)
    added = await client.post('/api/github/automation/targets', headers=admin_headers,
                              json={'account_id': mock_account['id'], 'group_label': '900002'})
    assert added.status_code == 201, added.text
    targets = [t for t in added.json()['targets'] if t['account_id'] == mock_account['id']]
    assert len(targets) == 2
    second = targets[-1]
    code = (await client.post('/api/github/automation/binding-code', headers=admin_headers, params={'target_id':second['id']})).json()['command']
    await bind_from_message(db, mock_account['id'], 900002, code)
    targets = [t for t in (await client.get('/api/github/automation', headers=admin_headers)).json()['targets'] if t['account_id'] == mock_account['id']]
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == 'notifier'))).user_id
    await sync_subscription(db, user_id)
    repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name == 'notifier/project-one'))
    return targets, repo


async def test_multiple_groups_receive_same_event_without_replacing_first(client, admin_headers, db, mock_account, notification_transport):
    from app.services.github.activity import ingest_activity

    targets, repo = await two_targets(client, admin_headers, db, mock_account)
    duplicate = await client.post('/api/github/automation/targets', headers=admin_headers,
                                  json={'account_id': mock_account['id'], 'group_label': '900002'})
    assert duplicate.status_code == 409
    result = await ingest_activity(db, repo, 'issues', {'action': 'opened', 'sender': {'login': 'notifier'},
                                  'issue': {'id': 99001, 'number': 1, 'title': '多群投递测试'}}, source='webhook')
    assert result['pushed'] == 2
    messages = account_manager.adapter(mock_account['id']).outbox
    assert {m['target'] for m in messages} == {123456789, 900002}
    state = (await client.get('/api/github/automation', headers=admin_headers)).json()
    assert state['qq_group'] == 123456789  # Legacy first-group fields remain stable.
    assert state['bound_target_count'] == 2
    rules = list(await db.scalars(select(PushRule).where(PushRule.account_id == mock_account['id'], PushRule.repository_id == repo.id)))
    assert {r.notification_target_id for r in rules if r.enabled} == {t['id'] for t in targets}


async def test_each_group_has_independent_binding_code(client, admin_headers, db, mock_account, notification_transport):
    targets, _ = await two_targets(client, admin_headers, db, mock_account)
    codes = []
    for target in targets:
        response = await client.post('/api/github/automation/binding-code', headers=admin_headers, params={'target_id': target['id']})
        assert response.status_code == 200
        codes.append(response.json()['command'])
    first = await bind_from_message(db, mock_account['id'], 991001, codes[0])
    second = await bind_from_message(db, mock_account['id'], 991002, codes[1])
    assert '已将当前群绑定' in first and '已将当前群绑定' in second
    state = (await client.get('/api/github/automation', headers=admin_headers)).json()
    bound = {t['id']: t['qq_group'] for t in state['targets']}
    assert bound[targets[0]['id']] == 991001
    assert bound[targets[1]['id']] == 991002
    assert '无效' in await bind_from_message(db, mock_account['id'], 991003, codes[0])


async def test_stop_or_remove_one_group_preserves_other_and_history(client, admin_headers, db, mock_account, notification_transport):
    from app.services.github.activity import ingest_activity

    targets, repo = await two_targets(client, admin_headers, db, mock_account)
    payload = {'action': 'opened', 'sender': {'login': 'notifier'}, 'issue': {'id': 99002, 'number': 2, 'title': '保留历史'}}
    assert (await ingest_activity(db, repo, 'issues', payload, source='webhook'))['pushed'] == 2
    history_before = len(list(await db.scalars(select(PushRecord).where(PushRecord.account_id == mock_account['id']))))
    second = targets[1]
    stopped = await client.put(f"/api/github/automation/targets/{second['id']}", headers=admin_headers,
                               json={'account_id': second['account_id'], 'group_label': second['group_label'], 'enabled': False})
    assert stopped.status_code == 200
    payload['issue']['id'] = 99003
    assert (await ingest_activity(db, repo, 'issues', payload, source='webhook'))['pushed'] == 1
    assert account_manager.adapter(mock_account['id']).outbox[-1]['target'] == 123456789
    removed = await client.delete(f"/api/github/automation/targets/{second['id']}", headers=admin_headers)
    assert removed.status_code == 200
    assert len(removed.json()['targets']) == 1
    history_after = len(list(await db.scalars(select(PushRecord).where(PushRecord.account_id == mock_account['id']))))
    assert history_after == history_before + 1


async def test_other_users_cannot_edit_or_bind_destinations(client, admin_headers, db, mock_account, notification_transport):
    from app.core.security import hash_password
    from app.models import Role, User

    targets, _ = await two_targets(client, admin_headers, db, mock_account)
    role = await db.scalar(select(Role).where(Role.name == 'operator'))
    user = User(username='notification-target-isolation', password_hash=hash_password('unit-target-pass'), role_id=role.id,
                email='target-isolation@example.com', display_name='Target isolation')
    db.add(user)
    await db.commit()
    login = await client.post('/api/auth/login', json={'username': user.username, 'password': 'unit-target-pass'})
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    target_id = targets[0]['id']
    assert not (await client.get('/api/github/automation', headers=headers)).json()['targets']
    assert (await client.post('/api/github/automation/binding-code', headers=headers, params={'target_id': target_id})).status_code == 400
    assert (await client.delete(f'/api/github/automation/targets/{target_id}', headers=headers)).status_code == 404
    changed = await client.put(f'/api/github/automation/targets/{target_id}', headers=headers,
                               json={'account_id': mock_account['id'], 'group_label': '123456789'})
    assert changed.status_code == 404


async def test_group_numbers_are_displayed_without_changing_routing(client, admin_headers, db, mock_account, notification_transport):
    from app.models import Group, Message

    await configure(client, admin_headers, mock_account)
    group = Group(account_id=mock_account['id'], group_number=123, name='群 123', display_number='123456789')
    db.add(group)
    db.add(Message(account_id=mock_account['id'], qq_group=123, message_type='group', direction='out', content='号码显示测试'))
    await db.commit()
    groups = (await client.get('/api/groups', headers=admin_headers, params={'account_id': mock_account['id'], 'keyword': '123456789'})).json()['items']
    shown = next(g for g in groups if g['group_number'] == 123)
    assert shown['display_number'] == '123456789'
    assert shown['display_name'] == 'QQ群 123456789'
    messages = (await client.get('/api/messages', headers=admin_headers, params={'keyword': '号码显示测试'})).json()['items']
    assert messages[0]['qq_group'] == 123
    assert messages[0]['group_display_number'] == '123456789'
    repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name == 'notifier/project-one'))
    rule = PushRule(repository_id=repo.id, account_id=mock_account['id'], qq_group=123)
    db.add(rule)
    event = GithubEvent(repository_id=repo.id, event_type='issues', dedupe_key='group-display-filter', payload={})
    db.add(event)
    await db.commit()
    record = PushRecord(repository_id=repo.id, rule_id=rule.id, event_id=event.id, account_id=mock_account['id'], qq_group=123, status='success')
    db.add(record)
    await db.commit()
    filtered = (await client.get('/api/github/push-records', headers=admin_headers, params={'qq_group': 123456789})).json()['items']
    assert any(r['id'] == record.id and r['qq_group_display'] == '123456789' for r in filtered)


async def test_archived_repository_is_not_reimported_by_subscription_sync(
    client, admin_headers, db, mock_account, notification_transport
):
    await configure(client, admin_headers, mock_account)
    user_id = (await db.scalar(select(UserGithubToken).where(UserGithubToken.login == "notifier"))).user_id
    await sync_subscription(db, user_id)
    repo = await db.scalar(select(GithubRepository).where(GithubRepository.full_name == "notifier/project-one"))
    assert repo is not None
    # 轮询/Webhook 已自动移除（这里直接删行模拟），归档仓库不得被下次同步重新导入。
    notification_transport["archived"].add("notifier/project-one")
    await db.delete(repo)
    await db.commit()
    cfg = await read_config(db, user_id)
    cfg["sync_requested"] = True
    await save_config(db, user_id, cfg)
    await sync_subscription(db, user_id)
    config = await read_config(db, user_id)
    assert config["sync_status"] == "ok", config
    assert config["monitored_count"] == 0
    assert not await db.scalar(select(GithubRepository).where(GithubRepository.full_name == "notifier/project-one"))
