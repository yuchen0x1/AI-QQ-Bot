"""原本"只播种、从不读取"的四个系统设置，现在必须真正生效。

覆盖：
- panel_title → 公开配置接口（登录页也能读到）
- github_default_poll_seconds → 新建仓库未指定间隔时的默认值
- push_default_template → 规则模板为空时的兜底
- ai_blocked_words → AI 回复内容过滤（与 BANNED_WORDS 合并）
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.http import set_transport

REPO_PAYLOAD = {
    "id": 7,
    "name": "widget",
    "full_name": "acme/widget",
    "html_url": "https://github.com/acme/widget",
    "description": "测试仓库",
    "default_branch": "main",
    "language": "Go",
    "stargazers_count": 3,
    "forks_count": 1,
    "owner": {"login": "acme"},
}


def _repo_payload(name: str) -> dict:
    return {**REPO_PAYLOAD, "name": name, "full_name": f"acme/{name}", "html_url": f"https://github.com/acme/{name}"}


@pytest.fixture()
def github_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = [p for p in path.split("/") if p]
        # /repos/{owner}/{name}
        if len(parts) == 3 and parts[0] == "repos":
            return httpx.Response(200, json=_repo_payload(parts[2]))
        if path.endswith("/releases"):
            return httpx.Response(200, json=[])
        if path.endswith("/tags"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "Not Found"})

    set_transport(httpx.MockTransport(handler))
    yield
    set_transport(None)


async def _set(client: httpx.AsyncClient, headers: dict, key: str, value) -> None:
    response = await client.put(f"/api/system/settings/{key}", headers=headers, json={"value": value})
    assert response.status_code == 200, response.text


async def test_public_config_exposes_panel_title(client: httpx.AsyncClient, admin_headers: dict) -> None:
    await _set(client, admin_headers, "panel_title", "示例机器人控制台")

    # 不带任何凭据也要能读到（登录页标题用）。
    response = await client.get("/api/system/config", headers={"Cookie": ""})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["panel_title"] == "示例机器人控制台"
    assert body["version"]


async def test_public_config_ignores_blank_title(client: httpx.AsyncClient, admin_headers: dict) -> None:
    await _set(client, admin_headers, "panel_title", "   ")
    body = (await client.get("/api/system/config")).json()
    assert body["panel_title"] == "QBot 控制台"


async def test_repo_uses_default_poll_interval_setting(
    client: httpx.AsyncClient, admin_headers: dict, github_transport
) -> None:
    await _set(client, admin_headers, "github_default_poll_seconds", 1234)

    created = await client.post(
        "/api/github/repos", headers=admin_headers, json={"url": "https://github.com/acme/poll-default"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["poll_interval_seconds"] == 1234


async def test_repo_explicit_interval_wins(client: httpx.AsyncClient, admin_headers: dict, github_transport) -> None:
    await _set(client, admin_headers, "github_default_poll_seconds", 1234)

    created = await client.post(
        "/api/github/repos",
        headers=admin_headers,
        json={"url": "https://github.com/acme/poll-explicit", "poll_interval_seconds": 300},
    )
    assert created.status_code == 201, created.text
    assert created.json()["poll_interval_seconds"] == 300


async def test_push_default_template_is_used_when_rule_has_none(
    client: httpx.AsyncClient, admin_headers: dict, mock_account: dict, github_transport
) -> None:
    from app.db.session import SessionLocal
    from app.models import GithubRelease, GithubRepository, PushRule
    from app.services.github.notify import build_message

    await _set(client, admin_headers, "push_default_template", "自定义默认模板 {full_name} {version}")

    repo_resp = await client.post(
        "/api/github/repos", headers=admin_headers, json={"url": "https://github.com/acme/template-repo"}
    )
    assert repo_resp.status_code == 201, repo_resp.text
    repo_id = repo_resp.json()["id"]

    async with SessionLocal() as db:
        repo = await db.get(GithubRepository, repo_id)
        release = await db.scalar(select(GithubRelease).where(GithubRelease.repository_id == repo_id))
        if release is None:
            release = GithubRelease(
                repository_id=repo_id, tag_name="v9.9.9", name="9.9.9", body="log", html_url="https://x/y"
            )
            db.add(release)
            await db.commit()
            await db.refresh(release)
        rule = PushRule(
            repository_id=repo_id,
            account_id=mock_account["id"],
            qq_group=10001,
            ai_summary=False,
            template=None,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)

        message = await build_message(db, repo, release, rule)

    assert message.startswith("自定义默认模板 acme/template-repo v9.9.9")


async def test_ai_blocked_words_setting_is_merged_with_group_words(db, client, admin_headers) -> None:
    """系统设置 ai_blocked_words 必须与群配置违禁词合并后用于过滤 AI 回复。"""
    from app.models import GroupSettings
    from app.services.bot_engine import effective_blocked_words

    response = await client.put(
        "/api/system/settings/ai_blocked_words", headers=admin_headers, json={"value": ["系统词", "重复词"]}
    )
    assert response.status_code == 200, response.text

    group_settings = GroupSettings(group_id=999999, banned_words=["群词", "重复词"])
    words = await effective_blocked_words(db, group_settings)

    assert "群词" in words
    assert "系统词" in words
    # 去重后只保留一份
    assert words.count("重复词") == 1
    # 群配置为空时系统设置仍生效
    assert "系统词" in await effective_blocked_words(db, None)