"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.qqbot_webhook import legacy_router as qqbot_webhook_legacy_router
from app.api.deps import client_ip
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.ratelimit import api_limiter, legacy_webhook_limiter
from app.core.version import APP_VERSION
from app.db.init_db import init_database
from app.db.session import SessionLocal
from app.services.account_manager import account_manager
from app.services.logs import write_log
from app.services.plugins import plugin_manager
from app.services.scheduler import scheduler_service

setup_logging()
logger = logging.getLogger("qbot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动 %s（env=%s）", settings.app_name, settings.env)
    try:
        settings.validate_security()
    except ValueError as exc:
        logger.error("安全配置校验失败：%s", exc)
        raise
    await init_database()
    async with SessionLocal() as db:
        stats = await plugin_manager.load_all(db)
        logger.info("插件加载结果：%s", stats)
    if settings.scheduler_enabled:
        await scheduler_service.start()
    started = await account_manager.boot_auto_start()
    if started:
        logger.info("已自动启动 %s 个账号", len(started))
    async with SessionLocal() as db:
        await write_log(db, level="INFO", category="system", message="平台启动完成")
    yield
    logger.info("正在关闭平台……")
    await account_manager.stop_all()
    from app.services.agent_mail import stop_login
    await stop_login()
    await scheduler_service.shutdown()
    async with SessionLocal() as db:
        await write_log(db, level="INFO", category="system", message="平台已停止", commit=True)


app = FastAPI(
    title=settings.app_name,
    version=APP_VERSION,
    description="多账号 QQ 机器人管理平台：账号隔离、群管理、AI 中心、GitHub 监控与自动推送",
    lifespan=lifespan,
    # 生产环境不公开交互式文档：它会把全部路由与 schema 暴露给未认证访问者。
    docs_url=None if settings.is_production else f"{settings.api_prefix}/docs",
    openapi_url=None if settings.is_production else f"{settings.api_prefix}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _path_matches(path: str, prefix: str) -> bool:
    """按路径段匹配，避免 /api/webhook 误豁免 /api/webhook-foo。"""
    return path == prefix or path.startswith(prefix + "/")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        client = client_ip(request)
        # 平台 Webhook 回调不受登录态限流约束：GitHub 与 QQ 官方机器人回调都由签名校验保护。
        callback_paths = (
            f"{settings.api_prefix}/webhook",
            f"{settings.api_prefix}/qqbot/webhook",
        )
        # 旧版根路径 /webhook（兼容把回调地址填成 https://域名/webhook）不在 API 前缀下，
        # 必须单独限流，否则任何人都能无限 POST 触发 JSON 解析和账号查询。
        is_legacy_callback = path == "/webhook" or path.startswith("/webhook/")
        if is_legacy_callback:
            allowed, retry_after = legacy_webhook_limiter.allow(client)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"请求过于频繁，请 {retry_after} 秒后重试"},
                    headers={"Retry-After": str(retry_after)},
                )
        elif path.startswith(settings.api_prefix) and not any(
            _path_matches(path, item) for item in callback_paths
        ):
            allowed, retry_after = api_limiter.allow(client)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"请求过于频繁，请 {retry_after} 秒后重试"},
                    headers={"Retry-After": str(retry_after)},
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


app.add_middleware(RateLimitMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    detail = str(exc) if settings.debug else "服务器内部错误，请查看系统日志"
    try:
        async with SessionLocal() as db:
            await write_log(
                db,
                level="ERROR",
                category="error",
                message=f"{request.method} {request.url.path} -> {type(exc).__name__}: {exc}",
            )
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(status_code=500, content={"detail": detail})


app.include_router(api_router, prefix=settings.api_prefix)
# 兼容把开放平台回调地址填成 https://域名/webhook 的部署方式。
app.include_router(qqbot_webhook_legacy_router)


@app.get("/")
async def root():
    payload = {
        "name": settings.app_name,
        "version": APP_VERSION,
        "health": f"{settings.api_prefix}/system/health",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if not settings.is_production:
        payload["docs"] = f"{settings.api_prefix}/docs"
    return payload
