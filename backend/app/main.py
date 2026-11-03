"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.ratelimit import api_limiter
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
    await scheduler_service.shutdown()
    async with SessionLocal() as db:
        await write_log(db, level="INFO", category="system", message="平台已停止", commit=True)


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="多账号 QQ 机器人管理平台：账号隔离、群管理、AI 中心、GitHub 监控与自动推送",
    lifespan=lifespan,
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(settings.api_prefix) and not path.startswith(f"{settings.api_prefix}/webhook"):
            client = request.client.host if request.client else "unknown"
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


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": f"{settings.api_prefix}/docs",
        "health": f"{settings.api_prefix}/system/health",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
