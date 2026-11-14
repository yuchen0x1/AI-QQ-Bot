"""数据库初始化：Alembic 负责建表/升级，本模块只负责幂等的种子数据写入。"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import ROLE_DEFS
from app.core.security import hash_password
from app.db.migrations import upgrade_schema
from app.db.session import SessionLocal
from app.models import Role, ScheduledTask, SystemSetting, User
from app.services.commands import seed_commands
from app.services.github.notify import DEFAULT_TEMPLATE
from app.services.plugins import plugin_manager

logger = logging.getLogger("qbot.init")

DEFAULT_SETTINGS: list[dict] = [
    {"key": "bot_super_admins", "value": [], "description": "拥有机器人最高权限的 QQ 号列表"},
    {"key": "ai_blocked_words", "value": [], "description": "AI 回复内容安全过滤词"},
    {"key": "github_default_poll_seconds", "value": 900, "description": "GitHub 默认轮询间隔（秒）"},
    {"key": "push_default_template", "value": DEFAULT_TEMPLATE, "description": "默认推送模板"},
    {"key": "panel_title", "value": "QBot 控制台", "description": "后台标题"},
    {"key": "auto_backup_keep", "value": 14, "description": "保留的备份数量"},
    {"key": "data_retention_days", "value": 3, "description": "消息与日志数据保留天数（0 表示永久）"},
    {"key": "alert_webhook_url", "value": "", "description": "异常告警 Webhook 地址（支持飞书/钉钉/企业微信/通用）"},
    {"key": "alert_channel_type", "value": "auto", "description": "告警通道类型：auto/feishu/dingtalk/wechat/custom"},
]

# 默认定时任务：仅在同名任务不存在时写入，管理员可随时在「定时任务」里停用或改时间。
# 没有这两个任务时，data_retention_days 与 auto_backup_keep 两个设置等于空转
# （前端却提示"每日凌晨自动清理"，与实际不符）。
DEFAULT_TASKS: list[dict] = [
    {
        "name": "每日数据清理",
        "task_type": "clean_expired_data",
        "schedule_kind": "cron",
        "cron_expr": "20 3 * * *",
        "payload": {},
    },
    {
        "name": "每日数据库备份",
        "task_type": "backup",
        "schedule_kind": "cron",
        "cron_expr": "40 3 * * *",
        "payload": {},
    },
]


async def seed() -> None:
    """写入内置角色、初始管理员、系统设置、命令与插件；可重复执行。"""
    async with SessionLocal() as db:
        for role_def in ROLE_DEFS:
            role = await db.scalar(select(Role).where(Role.name == role_def["name"]))
            if role:
                role.permissions = role_def["permissions"]
                role.description = role_def["description"]
                continue
            db.add(
                Role(
                    name=role_def["name"],
                    description=role_def["description"],
                    permissions=role_def["permissions"],
                    is_system=True,
                )
            )
        await db.commit()

        super_role = await db.scalar(select(Role).where(Role.name == "super_admin"))
        admin = await db.scalar(select(User).where(User.username == settings.admin_username))
        if not admin:
            db.add(
                User(
                    username=settings.admin_username,
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    display_name="超级管理员",
                    role_id=super_role.id if super_role else None,
                    is_active=True,
                )
            )
            await db.commit()
            logger.warning(
                "已创建初始管理员 %s，请登录后立即修改默认密码（当前默认密码来自环境变量 ADMIN_PASSWORD）",
                settings.admin_username,
            )

        for item in DEFAULT_SETTINGS:
            exists = await db.scalar(select(SystemSetting).where(SystemSetting.key == item["key"]))
            if not exists:
                db.add(SystemSetting(key=item["key"], value={"value": item["value"]}, description=item["description"]))
        await db.commit()

        # 默认任务按名称幂等写入；已存在（哪怕被停用）就不覆盖管理员的修改。
        for task_def in DEFAULT_TASKS:
            exists = await db.scalar(select(ScheduledTask).where(ScheduledTask.name == task_def["name"]))
            if not exists:
                db.add(ScheduledTask(**task_def, enabled=True, created_by="system"))
        await db.commit()

        await seed_commands(db)
        await plugin_manager.sync_to_db(db)
        logger.info("初始化数据已写入")


async def init_database() -> None:
    """先把 schema 升级到 Alembic head，再写入种子数据；schema 与数据互不混用。"""
    await upgrade_schema()
    await seed()


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(init_database())
