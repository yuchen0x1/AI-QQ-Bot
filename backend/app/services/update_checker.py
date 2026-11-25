"""在线版本检查：从 GitHub Releases 获取可信的发布元数据。

这是 Web/Docker 项目的更新入口：管理台提示新版本，部署环境再按发布资产执行
升级。浏览器不会下载或替换服务器文件，避免把 Web UI 误做成桌面安装器。
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.http import new_client
from app.core.version import APP_VERSION
from app.services.github.client import GithubClient, GithubError, parse_repo_url

SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
CACHE_SECONDS = 60
FAILURE_BACKOFF_SECONDS = 30
MAX_CACHE_ENTRIES = 32


@dataclass
class _ReleaseCache:
    payload: dict[str, Any] | None = None
    etag: str | None = None
    checked_at: float | None = None
    succeeded_at: float | None = None
    retry_at: float = 0
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


_cache: dict[tuple[str, str, str, str], _ReleaseCache] = {}


def clear_update_cache() -> None:
    """Discard metadata when a deployment or an isolated test changes its source."""
    _cache.clear()


def _iso(timestamp: float | None) -> str | None:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp is not None else None


def _retry_delay(headers: httpx.Headers, now: float) -> float:
    retry = headers.get("retry-after", "")
    try:
        delay = float(retry)
    except ValueError:
        try:
            delay = parsedate_to_datetime(retry).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            delay = 0
    try:
        if headers.get("x-ratelimit-remaining") == "0":
            delay = max(delay, float(headers.get("x-ratelimit-reset", "0")) - now)
    except ValueError:
        pass
    return max(FAILURE_BACKOFF_SECONDS, min(delay, 24 * 60 * 60))


class _MetadataError(GithubError):
    def __init__(self, message: str, status_code: int = 0, *, retry_after: float = FAILURE_BACKOFF_SECONDS):
        super().__init__(message, status_code, rate_limited=status_code in (403, 429))
        self.retry_after = retry_after


class _MetadataClient(GithubClient):
    """Keep conditional response headers without changing repository-monitor clients."""

    async def release_metadata(self, owner: str, name: str, channel: str, etag: str | None) -> tuple[Any, str | None]:
        path = f"/repos/{owner}/{name}/releases" + ("/latest" if channel == "stable" else "?per_page=50")
        headers = self._headers()
        if etag:
            headers["If-None-Match"] = etag
        try:
            async with new_client(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.get(self.api_base + path, headers=headers)
        except httpx.HTTPError as exc:
            raise _MetadataError(f"版本源暂时不可达：{type(exc).__name__}") from exc
        if response.status_code == 304:
            return None, response.headers.get("etag") or etag
        if response.status_code in (403, 429):
            raise _MetadataError(
                f"GitHub 更新源暂时拒绝请求（HTTP {response.status_code}），已按限流信息延后重试",
                response.status_code,
                retry_after=_retry_delay(response.headers, time.time()),
            )
        if response.status_code >= 300:
            raise _MetadataError(f"GitHub 更新源返回 HTTP {response.status_code}", response.status_code)
        try:
            return response.json(), response.headers.get("etag")
        except ValueError as exc:
            raise _MetadataError("GitHub 更新源返回无效 JSON") from exc


def parse_version(value: str) -> tuple[int, int, int, tuple[str, ...]]:
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"不是有效的 SemVer 版本：{value}")
    pre = tuple(match.group("pre").split(".")) if match.group("pre") else ()
    if any(not identifier or (identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0")) for identifier in pre):
        raise ValueError(f"不是有效的 SemVer 预发布版本：{value}")
    if "+" in str(value) and any(not part for part in str(value).split("+", 1)[1].split(".")):
        raise ValueError(f"不是有效的 SemVer 构建标识：{value}")
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
    if (parsed.scheme != "https" or parsed.hostname not in {"github.com", "objects.githubusercontent.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return None
    digest = str(asset.get("digest") or "").strip()
    digest = digest.lower() if re.fullmatch(r"sha256:[0-9a-f]{64}", digest, re.IGNORECASE) else ""
    return {
        "name": str(asset.get("name") or ""),
        "size": int(asset.get("size") or 0),
        "download_url": url,
        "sha256": digest.removeprefix("sha256:") if digest else None,
    }


def _release_payload(release: dict[str, Any], *, channel: str) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "").strip()
    version = tag.removeprefix("v")
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


def _select_release(raw: Any, channel: str) -> dict[str, Any]:
    if channel == "stable":
        if not isinstance(raw, dict) or raw.get("draft") or raw.get("prerelease"):
            raise ValueError("稳定通道拒绝草稿或预发布版本")
        if parse_version(str(raw.get("tag_name") or ""))[3]:
            raise ValueError("稳定通道拒绝预发布版本号")
        return raw
    if not isinstance(raw, list):
        raise ValueError("Beta 更新源格式无效")
    release = None
    for candidate in raw:
        if not isinstance(candidate, dict) or candidate.get("draft") or not candidate.get("prerelease"):
            continue
        tag = str(candidate.get("tag_name") or "")
        try:
            if not parse_version(tag)[3]:
                continue
            if release is None or compare_versions(tag, str(release["tag_name"])) > 0:
                release = candidate
        except ValueError:
            continue
    if release is None:
        raise GithubError("没有可用的 Beta Release", 404)
    return release


async def _refresh(entry: _ReleaseCache, owner: str, name: str, channel: str) -> None:
    entry.checked_at = time.time()
    try:
        client = _MetadataClient()
        try:
            raw, etag = await client.release_metadata(owner, name, channel, entry.etag)
        except GithubError as exc:
            if exc.status_code != 401 or not client.token:
                raise
            # A revoked repository-monitor token must not break public updates.
            raw, etag = await _MetadataClient(anonymous=True).release_metadata(owner, name, channel, entry.etag)
        if raw is None:
            if entry.payload is None:
                raise ValueError("更新源返回 304 但本机没有成功缓存")
        else:
            payload = _release_payload(_select_release(raw, channel), channel=channel)
            compare_versions(APP_VERSION, payload["version"])
            entry.payload = payload
        entry.etag = etag
        entry.succeeded_at = time.time()
        entry.retry_at = entry.succeeded_at + CACHE_SECONDS
        entry.error = None
    except Exception as exc:  # noqa: BLE001
        entry.error = str(exc) if isinstance(exc, (ValueError, GithubError)) else f"版本检查失败：{type(exc).__name__}"
        entry.retry_at = time.time() + getattr(exc, "retry_after", FAILURE_BACKOFF_SECONDS)


async def check_for_update(channel: str | None = None, *, force: bool = False) -> dict[str, Any]:
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
        "checked_at": None,
        "last_success_at": None,
        "cached": False,
        "stale": False,
        "cache_age_seconds": None,
        "next_check_at": None,
        "retry_after_seconds": 0,
    }
    try:
        owner, name = parse_repo_url(settings.update_repository)
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (owner, name)):
            raise ValueError("更新仓库地址无效")
        fingerprint = hashlib.sha256((settings.github_token or "").encode()).hexdigest()
        key = (settings.github_api_base.rstrip("/"), f"{owner}/{name}".lower(), requested_channel, fingerprint)
        if key not in _cache:
            if len(_cache) >= MAX_CACHE_ENTRIES:
                inactive = next((old for old, item in _cache.items() if item.task is None or item.task.done()), None)
                if inactive is not None:
                    _cache.pop(inactive)
            _cache[key] = _ReleaseCache()
        entry = _cache[key]
        now = time.time()
        # A manual check may refresh a successful cache, but never bypass a
        # server-directed backoff. Concurrent callers share one upstream task.
        due = now >= entry.retry_at or (force and entry.error is None)
        cached = not due and not (entry.task and not entry.task.done())
        if due and (entry.task is None or entry.task.done()):
            entry.task = asyncio.create_task(_refresh(entry, owner, name, requested_channel))
        if entry.task and not entry.task.done():
            await asyncio.shield(entry.task)
        now = time.time()
        base.update({
            "checked_at": _iso(entry.checked_at),
            "last_success_at": _iso(entry.succeeded_at),
            "cached": cached,
            "stale": bool(entry.error and entry.payload),
            "cache_age_seconds": max(0, int(now - entry.succeeded_at)) if entry.succeeded_at is not None else None,
            "next_check_at": _iso(entry.retry_at),
            "retry_after_seconds": max(0, int(entry.retry_at - now + 0.999)) if entry.error else 0,
            "error": entry.error,
            "ok": entry.error is None and entry.payload is not None,
        })
        if entry.payload is None:
            return base
        base.update(deepcopy(entry.payload))
        base["latest_version"] = entry.payload["version"]
        base["update_available"] = compare_versions(entry.payload["version"], APP_VERSION) > 0
        if not entry.error and compare_versions(entry.payload["version"], APP_VERSION) < 0:
            base["error"] = "远程版本低于当前版本，已忽略降级提示"
        return base
    except (ValueError, GithubError) as exc:
        base["error"] = str(exc)
        return base
    except Exception as exc:  # noqa: BLE001
        base["error"] = f"版本检查失败：{type(exc).__name__}"
        return base
