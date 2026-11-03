"""仓库 provider 抽象及 GitHub/Gitee 实现。"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote, urlparse

from app.services.github.client import GithubClient


class RepositoryProvider(Protocol):
    name: str

    async def get_repo(self, owner: str, name: str) -> dict[str, Any]: ...
    async def list_releases(self, owner: str, name: str, per_page: int = 20) -> list[dict[str, Any]]: ...
    async def list_tags(self, owner: str, name: str, per_page: int = 20) -> list[dict[str, Any]]: ...


class GiteeClient(GithubClient):
    """Gitee API 兼容客户端；返回字段归一化为 monitor 所需 GitHub 形状。"""

    name = "gitee"

    def __init__(self, token: str | None = None, *, api_base: str | None = None, timeout: float = 20.0) -> None:
        super().__init__(token, api_base=api_base or "https://gitee.com/api/v5", timeout=timeout)

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "QBot-Platform"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def _get(self, path: str, *, accept: str = "application/json") -> Any:
        # Gitee v5 对 token 使用 query 参数，避免与 GitHub Bearer 头差异。
        if self.token and "access_token=" not in path:
            path += ("&" if "?" in path else "?") + f"access_token={quote(self.token)}"
        return await super()._get(path, accept=accept)

    async def get_repo(self, owner: str, name: str) -> dict[str, Any]:
        result = await self._get(f"/repos/{owner}/{name}")
        return {
            "owner": {"login": result.get("owner", {}).get("login") or owner},
            "name": result.get("name") or name,
            "full_name": result.get("full_name") or f"{owner}/{name}",
            "html_url": result.get("html_url") or f"https://gitee.com/{owner}/{name}",
            "description": result.get("description"),
            "default_branch": result.get("default_branch"),
            "language": result.get("language"),
            "stargazers_count": result.get("stargazers_count") or result.get("stared_count") or 0,
            "forks_count": result.get("forks_count") or 0,
        }

    async def list_releases(self, owner: str, name: str, per_page: int = 20) -> list[dict[str, Any]]:
        rows = await self._get(f"/repos/{owner}/{name}/releases?page=1&per_page={per_page}")
        return [
            {**item, "tag_name": item.get("tag_name") or item.get("tag_name") or item.get("name")}
            for item in (rows or [])
        ]

    async def list_tags(self, owner: str, name: str, per_page: int = 20) -> list[dict[str, Any]]:
        return list(await self._get(f"/repos/{owner}/{name}/tags?page=1&per_page={per_page}") or [])


def parse_repository_url(url: str) -> tuple[str, str, str]:
    candidate = (url or "").strip()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.netloc or "").lower().split(":", 1)[0]
    parts = [part for part in parsed.path.split("/") if part]
    if host in {"github.com", "www.github.com"} and len(parts) >= 2:
        return "github", parts[0], parts[1].removesuffix(".git")
    if host in {"gitee.com", "www.gitee.com"} and len(parts) >= 2:
        return "gitee", parts[0], parts[1].removesuffix(".git")
    if len(parts) == 2 and host in {"", "localhost"}:
        return "github", parts[0], parts[1].removesuffix(".git")
    raise ValueError("无法解析仓库地址，请使用 GitHub 或 Gitee 仓库 URL")


def build_repository_provider(provider: str, token: str | None = None) -> RepositoryProvider:
    normalized = (provider or "github").strip().lower()
    if normalized == "github":
        return GithubClient(token)
    if normalized == "gitee":
        return GiteeClient(token)
    raise ValueError(f"不支持的仓库 provider：{provider}")
