"""API 路由聚合。"""

from fastapi import APIRouter

from app.api import (
    accounts,
    ai,
    auth,
    dashboard,
    github,
    github_oauth,
    groups,
    logs,
    messages,
    napcat,
    onebot,
    plugins,
    qqbot_webhook,
    requests,
    system,
    tasks,
    webhook,
    ws,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(accounts.router)
api_router.include_router(groups.router)
api_router.include_router(requests.router)
api_router.include_router(messages.router)
api_router.include_router(napcat.router)
api_router.include_router(ai.router)
api_router.include_router(github.router)
api_router.include_router(github_oauth.router)
api_router.include_router(tasks.router)
api_router.include_router(plugins.router)
api_router.include_router(logs.router)
api_router.include_router(system.router)
api_router.include_router(webhook.router)
api_router.include_router(qqbot_webhook.router)
api_router.include_router(onebot.router)
api_router.include_router(ws.router)
