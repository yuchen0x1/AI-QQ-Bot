"""Alembic schema 版本管理：启动时校验版本并升级到 head。

建表只允许由 Alembic 迁移完成；本模块不调用 ``Base.metadata.create_all``。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import BACKEND_DIR
from app.db.session import engine as default_engine

logger = logging.getLogger("qbot.migrations")

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
VERSION_TABLE = "alembic_version"


class SchemaVersionError(RuntimeError):
    """数据库 schema 版本无法确认，需要人工处理后才能启动。"""


@dataclass(frozen=True)
class SchemaState:
    tables: set[str]
    has_version_table: bool
    version: str | None


def alembic_config(database_url: str | None = None) -> Config:
    """构造 Alembic 配置；database_url 为空时沿用应用配置。"""
    config = Config(str(ALEMBIC_INI))
    # 启动路径不加载 alembic.ini 的 logging 配置，避免覆盖应用日志配置。
    config.config_file_name = None
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        config.attributes["database_url"] = database_url
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision(config: Config) -> str:
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise SchemaVersionError("Alembic 迁移目录中没有可用的 head 版本")
    return head


def known_revisions(config: Config) -> set[str]:
    return {script.revision for script in ScriptDirectory.from_config(config).walk_revisions()}


async def inspect_schema(engine: AsyncEngine) -> SchemaState:
    async with engine.connect() as conn:
        tables = set(await conn.run_sync(lambda sync_conn: sa.inspect(sync_conn).get_table_names()))
        if VERSION_TABLE not in tables:
            return SchemaState(tables=tables, has_version_table=False, version=None)
        rows = list((await conn.execute(sa.text(f"SELECT version_num FROM {VERSION_TABLE}"))).scalars())
        if not rows:
            return SchemaState(tables=tables, has_version_table=True, version="")
        if len(rows) > 1:
            raise SchemaVersionError(
                f"alembic_version 表存在多个版本记录 {rows!r}，数据库处于多分支状态，请人工核对迁移链后处理。"
            )
        return SchemaState(tables=tables, has_version_table=True, version=str(rows[0]))


def _assert_version_matches(config: Config, state: SchemaState, head: str) -> bool:
    """校验版本状态；返回是否需要执行 upgrade。"""
    app_tables = state.tables - {VERSION_TABLE}
    if not state.has_version_table:
        if app_tables:
            raise SchemaVersionError(
                "检测到未纳入 Alembic 版本管理的既有数据库（缺少 alembic_version 表）。"
                "请先备份并核对现有 schema；确认与当前迁移 head 一致后执行 "
                "`alembic stamp head`，不一致时请先补充缺失迁移。禁止使用 create_all 或删库重建。"
            )
        return True
    if not state.version:
        if app_tables:
            raise SchemaVersionError(
                "alembic_version 表为空，无法确认数据库版本。请备份并核对 schema 后执行 "
                "`alembic stamp <revision>`。"
            )
        return True
    if state.version not in known_revisions(config):
        raise SchemaVersionError(
            f"数据库记录的 Alembic 版本 {state.version!r} 不在当前迁移链中（head={head}）。"
            "请核对 alembic_version、部署分支与迁移文件，禁止直接重建数据库。"
        )
    return state.version != head


async def upgrade_schema(database_url: str | None = None) -> str:
    """校验并升级 schema 到 head，返回 head 版本号。"""
    config = alembic_config(database_url)
    head = head_revision(config)
    temp_engine: AsyncEngine | None = None
    target_engine = default_engine
    if database_url:
        temp_engine = create_async_engine(database_url, poolclass=pool.NullPool)
        target_engine = temp_engine
    try:
        state = await inspect_schema(target_engine)
        needs_upgrade = _assert_version_matches(config, state, head)
    finally:
        if temp_engine is not None:
            await temp_engine.dispose()

    if not needs_upgrade:
        logger.info("数据库 schema 已是最新版本 %s", head)
        return head
    if state.version:
        logger.info("数据库 schema 将从 %s 升级到 %s", state.version, head)
    else:
        logger.info("数据库 schema 将初始化到 %s", head)
    # env.py 使用 asyncio.run，必须放到独立线程中执行，避免与外层事件循环冲突。
    await asyncio.to_thread(command.upgrade, config, "head")
    return head
