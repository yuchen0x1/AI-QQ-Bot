"""全局配置：所有敏感项均来自环境变量，代码中不写死任何凭据。"""

from __future__ import annotations

import json
import os
import socket
from functools import lru_cache
from pathlib import Path

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
BASE_DIR = BACKEND_DIR.parent  # 项目根目录


def _split(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 基础 ----------
    app_name: str = "QBot 多账号智能 QQ 机器人管理平台"
    env: str = "development"
    debug: bool = False
    api_prefix: str = "/api"
    public_base_url: str = "http://localhost:8000"

    # ---------- NapCat 扫码登录 ----------
    # 可用 NAPCAT_INSTANCES_JSON 配置多个独立 NapCat 实例；单实例也可使用下面的字段。
    napcat_instances_json: str | None = None
    napcat_webui_url: str | None = None
    napcat_webui_token: str | None = None
    napcat_api_base: str | None = None
    napcat_ws_url: str | None = None
    napcat_access_token: str | None = None

    # ---------- QQ 官方机器人开放平台 ----------
    # 凭据存放于账号表（加密），这里只配置平台域名，便于私有化/网关环境覆盖。
    qqbot_token_url: str = "https://bots.qq.com/app/getAppAccessToken"
    qqbot_openapi_base: str = "https://api.bot.qq.com"
    qqbot_sandbox_openapi_base: str = "https://sandbox.api.sgroup.qq.com"
    # Webhook 事件推送允许的时间戳偏差（秒）；0 表示只验签名不校验新鲜度。
    qqbot_webhook_max_age_seconds: int = 300

    # ---------- 安全 ----------
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    access_token_expire_minutes: int = 720
    jwt_algorithm: str = "HS256"
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    rate_limit_per_minute: int = 240
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:8080"]

    # ---------- 初始管理员（仅首次初始化使用） ----------
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_email: str = "admin@example.com"

    # ---------- 数据库 ----------
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'qbot.db').as_posix()}"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------- Redis ----------
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False
    redis_queue_enabled: bool = False
    redis_queue_name: str = "qbot:tasks"
    instance_id: str = ""
    account_lease_seconds: int = 45
    account_lease_renew_seconds: int = 15

    # ---------- AI 运行时 ----------
    # 单个账号同时在途的 AI 请求上限：防止慢模型拖垮事件循环，也避免触发上游限流。
    # 同一群/同一私聊会话仍按顺序处理，只有不同会话之间才并发。
    ai_max_concurrency: int = 4

    # ---------- 调度 / 通知 ----------
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"
    github_api_base: str = "https://api.github.com"
    github_token: str | None = None
    github_poll_default_seconds: int = 900
    # GitHub OAuth App：可在网页端「GitHub → OAuth 配置」写入数据库（优先），也可用环境变量提供。
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    github_oauth_scopes: str = "read:user repo"
    # 留空则使用 PUBLIC_BASE_URL + /api/github/oauth/callback；反向代理或本地开发时可显式指定。
    github_oauth_redirect_uri: str | None = None
    push_max_retries: int = 3
    backup_dir: str = str(BASE_DIR / "backups")
    data_dir: str = str(BASE_DIR / "data")
    plugin_dir: str = str(BACKEND_DIR / "plugins")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: str | list[str]) -> list[str]:
        return _split(value)

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    @property
    def runtime_instance_id(self) -> str:
        return self.instance_id.strip() or f"{socket.gethostname()}:{os.getpid()}"

    def validate_security(self) -> None:
        """生产环境拒绝可预测的默认凭据，开发环境保持旧默认值兼容。"""
        if not self.is_production:
            return
        if len(self.secret_key) < 32 or self.secret_key.startswith("change-me"):
            raise ValueError("生产环境 SECRET_KEY 必须至少 32 个字符且不能使用默认值")
        if self.admin_password in {"admin123", "password", "changeme"} or len(self.admin_password) < 12:
            raise ValueError("生产环境 ADMIN_PASSWORD 必须至少 12 个字符且不能使用默认值")
        if "*" in self.cors_origins:
            raise ValueError("生产环境不允许使用通配 CORS_ORIGINS")

    def napcat_instances(self) -> list[dict[str, str]]:
        """Read fixed NapCat slots without exposing credentials in API responses."""
        if self.napcat_instances_json:
            try:
                raw = json.loads(self.napcat_instances_json)
            except json.JSONDecodeError as exc:
                raise ValueError("NAPCAT_INSTANCES_JSON 不是合法 JSON") from exc
            if not isinstance(raw, list):
                raise ValueError("NAPCAT_INSTANCES_JSON 必须是数组")
            items = raw
        elif self.napcat_webui_url and self.napcat_webui_token:
            items = [
                {
                    "id": "default",
                    "name": "NapCat 默认实例",
                    "webui_url": self.napcat_webui_url,
                    "webui_token": self.napcat_webui_token,
                    "api_base": self.napcat_api_base or "",
                    "ws_url": self.napcat_ws_url or "",
                    "access_token": self.napcat_access_token or "",
                }
            ]
        else:
            return []
        result: list[dict[str, str]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            required = ("webui_url", "webui_token")
            if any(not str(item.get(key) or "").strip() for key in required):
                continue
            result.append(
                {
                    "id": str(item.get("id") or f"napcat-{index + 1}"),
                    "name": str(item.get("name") or f"NapCat 实例 {index + 1}"),
                    "webui_url": str(item["webui_url"]),
                    "webui_token": str(item["webui_token"]),
                    "api_base": str(item.get("api_base") or ""),
                    "ws_url": str(item.get("ws_url") or ""),
                    "access_token": str(item.get("access_token") or ""),
                }
            )
        return result

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.backup_dir, os.path.dirname(self.database_url.split("///")[-1]) if self.database_url.startswith("sqlite") else ""):
            if path:
                Path(path).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
