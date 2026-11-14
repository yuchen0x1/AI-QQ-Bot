"""GitHub 动态 Markdown 卡片：渲染结构与「卡片失败降级纯文本」的推送保障。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.adapters.base import AdapterError
from app.models import GithubRelease, GithubRepository, PushRecord, PushRule
from app.services.account_manager import account_manager
from app.services.github.activity import ingest_activity, normalize_activity
from app.services.github.card import build_event_card, build_release_card
from app.services.github.notify import dispatch_release, render_release_message

# 与生产渲染保持一致的约束来源：官方 keyboard 最多 5 行、每行 5 个按钮。
MAX_ROWS = 5
MAX_BUTTONS_PER_ROW = 5


def make_repo(name: str) -> GithubRepository:
    return GithubRepository(
        owner="notifier",
        name=name,
        full_name=f"notifier/{name}",
        html_url=f"https://github.com/notifier/{name}",
        default_branch="main",
    )


def stub_event(card: dict, event_type: str = "push"):
    return type("EventStub", (), {"payload": {"card": card}, "event_type": event_type, "created_at": None})()


PUSH_PAYLOAD = {
    "ref": "refs/heads/main",
    "before": "a" * 40,
    "head": "b" * 40,
    "sender": {"login": "notifier"},
    "commits": [
        {"id": "b" * 40, "message": "fix(卡片): 修复渲染\n\n详细说明", "added": ["model/QQBot/interface.js"], "modified": [], "removed": []},
        {"id": "c" * 40, "message": "feat: 新增卡片开关", "added": [], "modified": ["app/services/github/card.py"], "removed": ["legacy/old.js"]},
    ],
}


def test_push_payload_collects_card_data():
    data = normalize_activity(make_repo("card-unit-push"), "push", PUSH_PAYLOAD)
    card = data["card"]
    assert card["kind"] == "push"
    assert card["branch"] == "main"
    assert card["commit_count"] == 2
    assert card["file_count"] == 3
    assert set(card["files"]) == {"model/QQBot/interface.js", "app/services/github/card.py", "legacy/old.js"}
    assert card["commits"][0]["sha"].startswith("bbbbbbb")
    assert card["stats"] is None  # webhook 推送不带行数统计，轮询路径才有


def test_push_card_markdown_and_keyboard_structure():
    repo = make_repo("card-unit-render")
    data = normalize_activity(repo, "push", PUSH_PAYLOAD)
    card = build_event_card(repo, stub_event(data["card"]))
    assert card is not None
    content = card["markdown"]["content"]
    for fragment in ("检测到新的代码推送", "notifier/card-unit-render", "分支：main", "提交内容", "变化文件",
                     "统计信息", "提交数量：2", "变化文件：3", "提交者：notifier", "bbbbbbb"):
        assert fragment in content
    # 官方 keyboard 约束：行数/每行按钮数不超限、id 唯一、跳转按钮字段齐全
    rows = card["keyboard"]["content"]["rows"]
    assert rows and len(rows) <= MAX_ROWS
    ids: list[str] = []
    for row in rows:
        assert 0 < len(row["buttons"]) <= MAX_BUTTONS_PER_ROW
        for button in row["buttons"]:
            ids.append(button["id"])
            assert button["action"]["type"] == 0
            assert button["action"]["permission"]["type"] == 2
            assert button["action"]["data"].startswith("https://")
            assert button["action"]["unsupport_tips"]
            assert button["render_data"]["label"]
    assert len(ids) == len(set(ids))


def test_card_neutralizes_code_fences_in_user_content():
    repo = make_repo("card-unit-fence")
    payload = {
        "ref": "refs/heads/dev",
        "before": "a" * 40,
        "head": "b" * 40,
        "sender": {"login": "notifier"},
        "commits": [{"id": "b" * 40, "message": "```sh\nrm -rf /```", "added": [], "modified": [], "removed": []}],
    }
    data = normalize_activity(repo, "push", payload)
    content = build_event_card(repo, stub_event(data["card"]))["markdown"]["content"]
    # 三连反引号被中和后，围栏数量保持偶数，代码块不会提前闭合
    assert len(content.split("```")) % 2 == 1


def test_generic_activity_card():
    repo = make_repo("card-unit-issue")
    payload = {"action": "opened", "sender": {"login": "notifier"},
               "issue": {"id": 99010, "number": 7, "title": "卡片测试 Issue", "body": "这是一个问题报告",
                         "html_url": "https://github.com/notifier/card-unit-issue/issues/7"}}
    data = normalize_activity(repo, "issues", payload)
    assert data["card"]["kind"] == "activity"
    card = build_event_card(repo, stub_event(data["card"], "issues"))
    content = card["markdown"]["content"]
    assert "Issue 动态" in content and "卡片测试 Issue" in content
    buttons = card["keyboard"]["content"]["rows"][0]["buttons"]
    assert any(b["action"]["data"].endswith("/issues/7") for b in buttons)


def test_old_events_without_card_data_render_nothing():
    """存量事件（无 card 数据）必须返回 None，保证旧数据回退纯文本不报错。"""
    repo = make_repo("card-unit-legacy")
    legacy = type("EventStub", (), {"payload": {"title": "旧事件", "content": "旧文本"}, "event_type": "push", "created_at": None})()
    assert build_event_card(repo, legacy) is None
    malformed = type("EventStub", (), {"payload": {"card": "坏数据"}, "event_type": "push", "created_at": None})()
    assert build_event_card(repo, malformed) is None
    assert build_event_card(repo, None) is None


async def _card_rule_fixture(client, admin_headers, db, mock_account, repo_name: str, group_id: int, *, card: bool = True):
    adapter = account_manager.adapter(mock_account["id"])
    adapter.groups[group_id] = {"group_id": group_id, "group_name": f"卡片测试群 {group_id}"}
    await account_manager.sync_groups(mock_account["id"])
    repo = GithubRepository(
        owner="notifier", name=repo_name, full_name=f"notifier/{repo_name}",
        html_url=f"https://github.com/notifier/{repo_name}", default_branch="main",
    )
    db.add(repo)
    await db.flush()
    rule = PushRule(repository_id=repo.id, account_id=mock_account["id"], qq_group=group_id,
                    event_types=["push"], markdown_card=card)
    db.add(rule)
    await db.commit()
    return adapter, repo, rule


async def test_dispatch_sends_markdown_card(client, admin_headers, db, mock_account):
    adapter, repo, rule = await _card_rule_fixture(client, admin_headers, db, mock_account, "card-dispatch", 123456789)
    result = await ingest_activity(db, repo, "push", PUSH_PAYLOAD, source="webhook")
    assert result["pushed"] == 1
    sent = adapter.outbox[-1]
    assert sent["target"] == 123456789
    assert sent["markdown"] and "检测到新的代码推送" in sent["markdown"]["content"]
    assert sent["keyboard"] and sent["keyboard"]["content"]["rows"]
    record = await db.scalar(select(PushRecord).where(PushRecord.rule_id == rule.id))
    assert record.status == "success"
    assert record.content  # 纯文本内容仍然入库，重发/降级都有底


async def test_dispatch_falls_back_to_text_when_card_rejected(client, admin_headers, db, mock_account, monkeypatch):
    adapter, repo, rule = await _card_rule_fixture(client, admin_headers, db, mock_account, "card-fallback", 123457789)
    original = type(adapter).send_group_message

    async def no_markdown(group_id, message, *, markdown=None, keyboard=None):
        if markdown is not None:
            raise AdapterError("markdown 权限未开通")
        return await original(adapter, group_id, message, markdown=None, keyboard=None)

    monkeypatch.setattr(adapter, "send_group_message", no_markdown)
    result = await ingest_activity(db, repo, "push", PUSH_PAYLOAD, source="webhook")
    assert result["pushed"] == 1  # 卡片被拒不影响送达
    sent = adapter.outbox[-1]
    assert sent["markdown"] is None and sent["keyboard"] is None
    assert "代码提交" in sent["message"]
    record = await db.scalar(select(PushRecord).where(PushRecord.rule_id == rule.id))
    assert record.status == "success"


async def test_text_rule_never_sends_card(client, admin_headers, db, mock_account):
    adapter, repo, rule = await _card_rule_fixture(client, admin_headers, db, mock_account, "card-text", 123458789, card=False)
    await ingest_activity(db, repo, "push", PUSH_PAYLOAD, source="webhook")
    sent = adapter.outbox[-1]
    assert sent["markdown"] is None and sent["keyboard"] is None
    assert sent["target"] == 123458789


def make_release(repo_id: int, tag: str = "v1.3.0") -> GithubRelease:
    return GithubRelease(
        repository_id=repo_id,
        tag_name=tag,
        name=tag,
        body="## 本版更新\n\n- 新增 Markdown 卡片推送\n- 修复若干问题",
        html_url=f"https://github.com/notifier/card-rel/releases/tag/{tag}",
        published_at=datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc),
        assets=[{"name": "app-setup.exe", "size": 10485760}],
    )


async def test_release_render_produces_text_and_card(client, admin_headers, db):
    from app.models import Account

    repo = make_repo("card-rel")
    db.add(repo)
    await db.flush()
    release = make_release(repo.id)
    db.add(release)
    # 外键已启用：推送规则必须引用真实存在的账号。
    account = Account(
        account_id="card-rel-test", name="card-rel-test", qq_number=900003, protocol="qq_official", enabled=False
    )
    db.add(account)
    await db.flush()
    rule = PushRule(repository_id=repo.id, account_id=account.id, qq_group=123459789, event_types=["release"],
                    markdown_card=True, ai_summary=False)
    db.add(rule)
    await db.commit()

    rendered = await render_release_message(db, repo, release, rule)
    assert "v1.3.0" in rendered["content"]  # 文本版照常渲染
    card = rendered["card"]
    assert card["kind"] == "release"
    assert card["version"] == "v1.3.0"
    assert "新增 Markdown 卡片推送" in card["changelog"]
    # 正文未列出资产 → 卡片带独立下载段
    assert card["downloads"] and "app-setup.exe" in card["downloads"]

    built = build_release_card(repo, card)
    md = built["markdown"]["content"]
    assert "发布新版本 v1.3.0" in md and "更新内容" in md and "下载与发布资产" in md
    buttons = built["keyboard"]["content"]["rows"][0]["buttons"]
    assert any(b["action"]["data"].endswith("/releases/tag/v1.3.0") for b in buttons)

    # 开关关闭时卡片数据相应留空
    rule.include_changelog = False
    rule.include_downloads = False
    card2 = (await render_release_message(db, repo, release, rule))["card"]
    assert card2["changelog"] is None and card2["downloads"] is None
    built2 = build_release_card(repo, card2)
    assert "已关闭更新日志推送" in built2["markdown"]["content"]
    assert "下载与发布资产" not in built2["markdown"]["content"]
    # 存量记录的坏数据回退纯文本
    assert build_release_card(repo, {"kind": "activity"}) is None


async def test_dispatch_release_sends_markdown_card(client, admin_headers, db, mock_account):
    adapter = account_manager.adapter(mock_account["id"])
    adapter.groups[123459789] = {"group_id": 123459789, "group_name": "发布卡片测试群"}
    await account_manager.sync_groups(mock_account["id"])
    repo = make_repo("card-rel-dispatch")
    db.add(repo)
    await db.flush()
    release = make_release(repo.id)
    db.add(release)
    rule = PushRule(repository_id=repo.id, account_id=mock_account["id"], qq_group=123459789,
                    event_types=["release"], markdown_card=True, ai_summary=False)
    db.add(rule)
    await db.commit()

    records = await dispatch_release(db, repo, release, source="webhook")
    assert records and records[0].status == "success"
    assert records[0].card_payload and records[0].card_payload["kind"] == "release"
    sent = adapter.outbox[-1]
    assert sent["target"] == 123459789
    assert sent["markdown"] and "发布新版本 v1.3.0" in sent["markdown"]["content"]
    assert sent["keyboard"] and sent["keyboard"]["content"]["rows"]

    # 失败记录重试时依旧走卡片（card_payload 随记录持久化）
    record = records[0]
    record.status = "failed"
    await db.commit()
    from app.services.github.notify import retry_failed_pushes

    stats = await retry_failed_pushes(db)
    assert stats["success"] == 1
    assert adapter.outbox[-1]["markdown"] and "发布新版本 v1.3.0" in adapter.outbox[-1]["markdown"]["content"]


async def test_dispatch_release_falls_back_to_text_when_card_rejected(client, admin_headers, db, mock_account, monkeypatch):
    adapter = account_manager.adapter(mock_account["id"])
    adapter.groups[123460789] = {"group_id": 123460789, "group_name": "发布降级测试群"}
    await account_manager.sync_groups(mock_account["id"])
    repo = make_repo("card-rel-fallback")
    db.add(repo)
    await db.flush()
    release = make_release(repo.id, "v2.0.0")
    db.add(release)
    rule = PushRule(repository_id=repo.id, account_id=mock_account["id"], qq_group=123460789,
                    event_types=["release"], markdown_card=True, ai_summary=False)
    db.add(rule)
    await db.commit()

    original = type(adapter).send_group_message

    async def no_markdown(group_id, message, *, markdown=None, keyboard=None):
        if markdown is not None:
            raise AdapterError("markdown 权限未开通")
        return await original(adapter, group_id, message, markdown=None, keyboard=None)

    monkeypatch.setattr(adapter, "send_group_message", no_markdown)
    records = await dispatch_release(db, repo, release, source="webhook")
    assert records and records[0].status == "success"  # 卡片被拒不影响送达
    sent = adapter.outbox[-1]
    assert sent["markdown"] is None and sent["keyboard"] is None
    assert "GitHub 项目更新通知" in sent["message"]
