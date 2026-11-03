"""GitHub API 客户端：限流感知、Token 支持、错误透传。"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.http import new_client

logger = logging.getLogger("qbot.github")

REPO_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.\-]+)/(?P<name>[\w.\-]+?)(?:\.git)?/?$", re.I)


class GithubError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.rate_limited = rate_limited


def parse_repo_url(url: str) -> tuple[str, str]:
    candidate = (url or "").strip()
    match = REPO_URL_RE.match(candidate)
    if match:
        return match.group("owner"), match.group("name")
    parsed = urlparse(candidate)
    parts = [p for p in parsed.path.split("/") if p]
    if "github.com" in (parsed.netloc or "") and len(parts) >= 2:
        return parts[0], parts[1].replace(".git", "")
    if "/" in candidate and " " not in candidate:
        owner, _, name = candidate.partition("/")
        return owner.strip(), name.strip()
    raise ValueError("无法解析 GitHub 仓库地址，请使用 https://github.com/用户名/仓库名 格式")


class GithubClient:
    name = "github"

    def __init__(self, token: str | None = None, *, api_base: str | None = None, timeout: float = 20.0) -> None:
        self.token = token or settings.github_token
        self.api_base = (api_base or settings.github_api_base).rstrip("/")
        self.timeout = timeout
        self.rate_limit_remaining: int | None = None
        self.rate_limit_reset: int | None = None

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "QBot-Platform"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _get(self, path: str, *, accept: str = "application/vnd.github+json") -> Any:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        try:
            async with new_client(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._headers(accept))
        except httpx.HTTPError as exc:
            raise GithubError(f"请求 GitHub 失败：{exc}") from exc
        self.rate_limit_remaining = int(response.headers.get("x-ratelimit-remaining", -1))
        self.rate_limit_reset = int(response.headers.get("x-ratelimit-reset", 0) or 0)
        if response.status_code == 404:
            raise GithubError("仓库不存在或无权访问（404）", 404)
        if response.status_code in (403, 429):
            message = "GitHub API 触发限流，请配置 Token 或稍后重试" if self.rate_limit_remaining == 0 else "GitHub 拒绝访问"
            raise GithubError(message, response.status_code, rate_limited=True)
        if response.status_code >= 400:
            raise GithubError(f"GitHub 返回 HTTP {response.status_code}: {response.text[:200]}", response.status_code)
        if accept.endswith("json") or "json" in accept:
            return response.json()
        return response.text

    async def get_repo(self, owner: str, name: str) -> dict[str, Any]:
        return await self._get(f"/repos/{owner}/{name}")

    async def list_releases(self, owner: str, name: str, per_page: int = 20) -> list[dict[str, Any]]:
        data = await self._get(f"/repos/{owner}/{name}/releases?per_page={per_page}")
        return list(data or [])

    async def get_latest_release(self, owner: str, name: str) -> dict[str, Any]:
        return await self._get(f"/repos/{owner}/{name}/releases/latest")

    async def list_tags(self, owner: str, name: str, per_page: int = 20) -> list[dict[str, Any]]:
        return list(await self._get(f"/repos/{owner}/{name}/tags?per_page={per_page}") or [])

    async def list_commits(self, owner: str, name: str, per_page: int = 5) -> list[dict[str, Any]]:
        return list(await self._get(f"/repos/{owner}/{name}/commits?per_page={per_page}") or [])
