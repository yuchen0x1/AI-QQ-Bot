"""在线更新版本比较、Release 资产安全过滤和 API 回归。"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.http import set_transport
from app.services.update_checker import compare_versions, check_for_update, parse_version


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
