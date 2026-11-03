"""数据库初始化：建表、内置角色、管理员、系统配置、内置命令、插件同步。"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import ROLE_DEFS
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.models import Base, Role, SystemSetting, User
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
]


async def create_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库表结构已就绪")


async def seed() -> None:
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

        await seed_commands(db)
        await plugin_manager.sync_to_db(db)
        logger.info("初始化数据已写入")


async def init_database(*, create_tables: bool = True) -> None:
    if create_tables:
        await create_schema()
    await seed()


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(init_database())
