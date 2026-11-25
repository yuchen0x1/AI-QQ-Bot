"""在线更新版本比较、Release 资产安全过滤和 API 回归。"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import settings
from app.core.http import set_transport
from app.services.update_checker import clear_update_cache, compare_versions, check_for_update, parse_version


@pytest.fixture(autouse=True)
def isolated_update_source():
    clear_update_cache()
    yield
    clear_update_cache()


def test_semver_comparison_handles_prerelease_and_v_prefix() -> None:
    assert parse_version("v1.2.3") == (1, 2, 3, ())
    assert compare_versions("1.2.3", "1.2.3") == 0
    assert compare_versions("1.2.4", "1.2.3") == 1
    assert compare_versions("1.2.3", "1.2.4") == -1
    assert compare_versions("1.2.3", "1.2.3-beta.1") == 1
    assert compare_versions("1.2.3-beta.2", "1.2.3-beta.10") == -1


async def test_check_for_update_reads_release_and_filters_untrusted_assets() -> None:
    original_repo = settings.update_repository
    settings.update_repository = "yuchen0x1/AI-QQ-Bot"
    release = {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v9.9.9",
        "body": "安全修复",
        "published_at": "2026-11-12T00:00:00Z",
        "prerelease": False,
        "draft": False,
        "assets": [
            {
                "name": "qbot.tar.gz",
                "size": 42,
                "browser_download_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/download/v9.9.9/qbot.tar.gz",
                "digest": "sha256:" + "a" * 64,
            },
            {
                "name": "evil.bin",
                "size": 10,
                "browser_download_url": "http://attacker.invalid/evil.bin",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/repos/yuchen0x1/AI-QQ-Bot/releases/latest")
        return httpx.Response(200, json=release)

    set_transport(httpx.MockTransport(handler))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
        settings.update_repository = original_repo
    assert result["ok"] is True
    assert result["update_available"] is True
    assert result["latest_version"] == "9.9.9"
    assert len(result["assets"]) == 1
    assert result["assets"][0]["sha256"] == "a" * 64


async def test_check_for_update_failure_does_not_raise() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    set_transport(httpx.MockTransport(handler))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
    assert result["ok"] is False
    assert result["update_available"] is False
    assert result["error"]


async def test_beta_channel_only_accepts_prereleases() -> None:
    """Beta must never silently fall back to a stable release."""
    original_repo = settings.update_repository
    original_channel = settings.update_channel
    settings.update_repository = "yuchen0x1/AI-QQ-Bot"
    settings.update_channel = "beta"
    releases = [
        {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v9.9.9",
            "body": "stable",
            "published_at": "2026-11-23T00:00:00Z",
            "prerelease": False,
            "draft": False,
            "assets": [],
        },
        {
            "tag_name": "v1.5.3-beta.1",
            "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v1.5.3-beta.1",
            "body": "beta",
            "published_at": "2026-11-20T00:00:00Z",
            "prerelease": True,
            "draft": False,
            "assets": [],
        },
        {
            "tag_name": "v1.5.4-beta.1",
            "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v1.5.4-beta.1",
            "body": "draft beta",
            "published_at": "2026-11-24T00:00:00Z",
            "prerelease": True,
            "draft": True,
            "assets": [],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/repos/yuchen0x1/AI-QQ-Bot/releases")
        assert request.url.params.get("per_page") == "50"
        return httpx.Response(200, json=releases)

    set_transport(httpx.MockTransport(handler))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
        settings.update_repository = original_repo
        settings.update_channel = original_channel
    assert result["ok"] is True
    assert result["channel"] == "beta"
    assert result["latest_version"] == "1.5.3-beta.1"
    assert result["prerelease"] is True


async def test_beta_channel_without_prerelease_reports_no_release() -> None:
    original_repo = settings.update_repository
    original_channel = settings.update_channel
    settings.update_repository = "yuchen0x1/AI-QQ-Bot"
    settings.update_channel = "beta"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v9.9.9",
            "published_at": "2026-11-23T00:00:00Z",
            "prerelease": False,
            "draft": False,
            "assets": [],
        }])

    set_transport(httpx.MockTransport(handler))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
        settings.update_repository = original_repo
        settings.update_channel = original_channel
    assert result["ok"] is False
    assert result["latest_version"] is None


async def test_check_for_update_retries_anonymously_after_invalid_global_token() -> None:
    original_token = settings.github_token
    settings.github_token = "expired-token"
    requests: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        has_auth = "authorization" in request.headers
        requests.append(has_auth)
        if has_auth:
            return httpx.Response(401, json={"message": "Bad credentials"})
        return httpx.Response(200, json={
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v9.9.9",
            "published_at": "2026-11-12T00:00:00Z",
            "prerelease": False,
            "assets": [],
        })

    set_transport(httpx.MockTransport(handler))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
        settings.github_token = original_token
    assert result["ok"] is True
    assert requests == [True, False]


async def test_update_endpoint_returns_safe_release_metadata(client, admin_headers) -> None:
    release = {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v9.9.9",
        "body": "更新日志",
        "published_at": "2026-11-12T00:00:00Z",
        "prerelease": False,
        "draft": False,
        "assets": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/repos/yuchen0x1/AI-QQ-Bot/releases/latest")
        return httpx.Response(200, json=release)

    set_transport(httpx.MockTransport(handler))
    try:
        response = await client.get("/api/system/update", headers=admin_headers)
    finally:
        set_transport(None)
    assert response.status_code == 200
    assert response.json()["update_available"] is True
    assert response.json()["latest_version"] == "9.9.9"


def release(version="9.9.9", **overrides):
    return {
        "tag_name": "v" + version,
        "html_url": f"https://github.com/yuchen0x1/AI-QQ-Bot/releases/tag/v{version}",
        "prerelease": False,
        "draft": False,
        "assets": [],
        **overrides,
    }


async def test_concurrent_pages_share_one_upstream_check_and_result_is_copied():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=release(), headers={"ETag": '"release-1"'})

    set_transport(httpx.MockTransport(handler))
    try:
        results = await asyncio.gather(*(check_for_update() for _ in range(12)))
        results[0]["assets"].append({"name": "mutated"})
        cached = await check_for_update()
    finally:
        set_transport(None)
    assert calls == 1
    assert all(result["ok"] for result in results)
    assert cached["cached"] is True
    assert cached["assets"] == []
    assert cached["checked_at"] and cached["last_success_at"]


async def test_conditional_check_refreshes_timestamp_without_losing_release(monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr("app.services.update_checker.time.time", lambda: clock[0])
    calls = []

    def handler(request):
        calls.append(request.headers.get("if-none-match"))
        if len(calls) == 1:
            return httpx.Response(200, json=release(), headers={"ETag": '"release-1"'})
        return httpx.Response(304, headers={"ETag": '"release-1"'})

    set_transport(httpx.MockTransport(handler))
    try:
        first = await check_for_update()
        clock[0] += 61
        refreshed = await check_for_update()
    finally:
        set_transport(None)
    assert calls == [None, '"release-1"']
    assert refreshed["latest_version"] == first["latest_version"]
    assert refreshed["last_success_at"] != first["last_success_at"]
    assert refreshed["stale"] is False


@pytest.mark.parametrize("status", [403, 429])
async def test_rate_limit_retains_labelled_stale_data_and_force_respects_retry_after(monkeypatch, status):
    clock = [1_800_000_000.0]
    monkeypatch.setattr("app.services.update_checker.time.time", lambda: clock[0])
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1 or calls == 3:
            return httpx.Response(200, json=release("9.9.9" if calls == 1 else "9.9.10"))
        return httpx.Response(status, json={"message": "limited"}, headers={"Retry-After": "120"})

    set_transport(httpx.MockTransport(handler))
    try:
        original = await check_for_update()
        clock[0] += 61
        stale = await check_for_update()
        still_stale = await check_for_update(force=True)
        assert calls == 2
        clock[0] += 121
        recovered = await check_for_update()
    finally:
        set_transport(None)
    assert stale["ok"] is False and stale["stale"] is True
    assert stale["latest_version"] == "9.9.9"
    assert stale["last_success_at"] == original["last_success_at"]
    assert stale["retry_after_seconds"] == 120 and str(status) in stale["error"]
    assert still_stale["cached"] is True
    assert recovered["ok"] is True and recovered["latest_version"] == "9.9.10"


async def test_expired_token_never_follows_redirect_or_retries_non_401(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "expired-token")
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "http://127.0.0.1/metadata"})

    set_transport(httpx.MockTransport(handler))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
    assert len(calls) == 1 and result["ok"] is False
    assert "307" in result["error"]


async def test_cache_isolated_by_channel_repository_and_token(monkeypatch):
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers.get("authorization")))
        payload = [release("9.9.9-beta.1", prerelease=True)] if request.url.path.endswith("/releases") else release()
        return httpx.Response(200, json=payload)

    set_transport(httpx.MockTransport(handler))
    try:
        await check_for_update()
        await check_for_update("beta")
        monkeypatch.setattr(settings, "update_repository", "other/repository")
        await check_for_update()
        monkeypatch.setattr(settings, "github_token", "changed-token")
        await check_for_update()
    finally:
        set_transport(None)
    assert len(calls) == 4


@pytest.mark.parametrize("bad", ["1.2.3-beta..1", "1.2.3-01", "1.2.3+build..1"])
def test_invalid_semver_identifiers_rejected(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


@pytest.mark.parametrize("overrides", [{"draft": True}, {"prerelease": True}, {"tag_name": "v9.9.9-beta.1"}])
async def test_stable_never_accepts_draft_or_prerelease(overrides):
    set_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=release(**overrides))))
    try:
        result = await check_for_update()
    finally:
        set_transport(None)
    assert result["ok"] is False and result["update_available"] is False


async def test_offline_recovery_and_cancelled_caller_do_not_kill_shared_check(monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr("app.services.update_checker.time.time", lambda: clock[0])
    entered = asyncio.Event()
    complete = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("offline")
        entered.set()
        await complete.wait()
        return httpx.Response(200, json=release())

    set_transport(httpx.MockTransport(handler))
    try:
        offline = await check_for_update()
        assert offline["ok"] is False and offline["latest_version"] is None
        clock[0] += 31
        abandoned = asyncio.create_task(check_for_update())
        await entered.wait()
        survivor = asyncio.create_task(check_for_update())
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        complete.set()
        result = await survivor
    finally:
        set_transport(None)
    assert calls == 2 and result["ok"] is True


async def test_legacy_api_schema_remains_and_stale_metadata_cannot_enable_install(client, admin_headers, monkeypatch):
    from app.services import update_installer

    async def installer():
        return {"available": True, "job": None}

    monkeypatch.setattr(update_installer, "installer_state", installer)
    calls = 0
    native = "qbot-ai-9.9.9-native.tar.gz"

    def handler(request):
        nonlocal calls
        calls += 1
        if calls > 1:
            return httpx.Response(503, json={"message": "offline"})
        return httpx.Response(200, json=release(assets=[{
            "name": name, "size": 1, "digest": "sha256:" + "a" * 64,
            "browser_download_url": f"https://github.com/yuchen0x1/AI-QQ-Bot/releases/download/v9.9.9/{name}",
        } for name in (native, "provenance.sigstore.json")]))

    set_transport(httpx.MockTransport(handler))
    try:
        first = (await client.get("/api/system/update", headers=admin_headers)).json()
        stale = (await client.get("/api/system/update?force=true", headers=admin_headers)).json()
    finally:
        set_transport(None)
    legacy = {"ok", "current_version", "channel", "repository", "check_interval_minutes", "update_available",
              "latest_version", "release_url", "release_notes", "published_at", "assets", "error"}
    assert legacy <= first.keys() and legacy <= stale.keys()
    assert first["installable"] is True
    assert stale["stale"] is True and stale["installable"] is False
    assert stale["assets"] == first["assets"] and stale["last_success_at"] == first["last_success_at"]


@pytest.mark.parametrize("headers,expected", [
    ({"Retry-After": "Fri, 15 Jan 2027 08:02:00 GMT"}, 120),
    ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800000300"}, 300),
    ({"Retry-After": "not-a-date"}, 30),
])
async def test_rate_limit_header_formats_control_real_retry_gate(monkeypatch, headers, expected):
    monkeypatch.setattr("app.services.update_checker.time.time", lambda: 1_800_000_000.0)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429, headers=headers)

    set_transport(httpx.MockTransport(handler))
    try:
        first = await check_for_update()
        await check_for_update(force=True)
    finally:
        set_transport(None)
    assert first["retry_after_seconds"] == expected
    assert len(calls) == 1
