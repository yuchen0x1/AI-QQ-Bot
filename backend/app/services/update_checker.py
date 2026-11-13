"""在线版本检查：从 GitHub Releases 获取可信的发布元数据。

这是 Web/Docker 项目的更新入口：管理台提示新版本，部署环境再按发布资产执行
升级。浏览器不会下载或替换服务器文件，避免把 Web UI 误做成桌面安装器。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.core.version import APP_VERSION
from app.services.github.client import GithubClient, GithubError, parse_repo_url

SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def parse_version(value: str) -> tuple[int, int, int, tuple[str, ...]]:
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"不是有效的 SemVer 版本：{value}")
    pre = tuple(match.group("pre").split(".")) if match.group("pre") else ()
    return int(match.group("major")), int(match.group("minor")), int(match.group("patch")), pre


def compare_versions(left: str, right: str) -> int:
    """按 SemVer 比较，返回 -1/0/1；稳定版始终高于同核心版本预发布版。"""
    a = parse_version(left)
    b = parse_version(right)
    for index in range(3):
        if a[index] != b[index]:
            return 1 if a[index] > b[index] else -1
    if not a[3] and not b[3]:
        return 0
    if not a[3]:
        return 1
    if not b[3]:
        return -1
    for left_id, right_id in zip(a[3], b[3]):
        if left_id == right_id:
            continue
        left_num, right_num = left_id.isdigit(), right_id.isdigit()
        if left_num and right_num:
            return 1 if int(left_id) > int(right_id) else -1
        if left_num != right_num:
            return -1 if left_num else 1
        return 1 if left_id > right_id else -1
    if len(a[3]) == len(b[3]):
        return 0
    return 1 if len(a[3]) > len(b[3]) else -1


def _safe_asset(asset: dict[str, Any]) -> dict[str, Any] | None:
    url = str(asset.get("browser_download_url") or "").strip()
    parsed = urlparse(url)
    # Release assets must remain HTTPS GitHub URLs. Do not expose arbitrary URLs
    # supplied by a compromised/misconfigured release as download targets.
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "objects.githubusercontent.com"}:
        return None
    digest = str(asset.get("digest") or "").strip()
    if digest and not digest.lower().startswith("sha256:"):
        digest = ""
    return {
        "name": str(asset.get("name") or ""),
        "size": int(asset.get("size") or 0),
        "download_url": url,
        "sha256": digest.removeprefix("sha256:") if digest else None,
    }


def _release_payload(release: dict[str, Any], *, channel: str) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "").strip()
    version = tag.lstrip("v")
    assets = [item for raw in release.get("assets") or [] if (item := _safe_asset(raw))]
    return {
        "version": version,
        "tag": tag,
        "channel": channel,
        "release_url": str(release.get("html_url") or ""),
        "release_notes": str(release.get("body") or "").strip(),
        "published_at": release.get("published_at"),
        "prerelease": bool(release.get("prerelease")),
        "assets": assets,
    }


async def check_for_update(channel: str | None = None) -> dict[str, Any]:
    requested_channel = (channel or settings.update_channel or "stable").strip().lower()
    if requested_channel not in {"stable", "beta"}:
        requested_channel = "stable"
    base = {
        "ok": False,
        "current_version": APP_VERSION,
        "channel": requested_channel,
        "repository": settings.update_repository,
        "check_interval_minutes": max(0, int(settings.update_check_interval_minutes)),
        "update_available": False,
        "latest_version": None,
        "release_url": None,
        "release_notes": "",
        "published_at": None,
        "assets": [],
        "error": None,
    }
    try:
        owner, name = parse_repo_url(settings.update_repository)
        client = GithubClient()
        if requested_channel == "stable":
            release = await client.get_latest_release(owner, name)
        else:
            releases = await client.list_releases(owner, name, per_page=50)
            candidates = [r for r in releases if not r.get("draft")]
            candidates.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
            release = next((r for r in candidates if r.get("prerelease") or r.get("tag_name")), None)
            if not release:
                raise GithubError("没有可用的 Beta Release", 404)
        payload = _release_payload(release, channel=requested_channel)
        compare_versions(APP_VERSION, payload["version"])
        base.update(payload)
        base["latest_version"] = payload["version"]
        base["ok"] = True
        base["update_available"] = compare_versions(payload["version"], APP_VERSION) > 0
        if compare_versions(payload["version"], APP_VERSION) < 0:
            base["error"] = "远程版本低于当前版本，已忽略降级提示"
        return base
    except (ValueError, GithubError) as exc:
        base["error"] = str(exc)
        return base
    except Exception as exc:  # noqa: BLE001
        base["error"] = f"版本检查失败：{type(exc).__name__}"
        return base
