"""异步数据库引擎与会话工厂。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    future=True,
    pool_pre_ping=not _is_sqlite,
    **({} if _is_sqlite else {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow}),
)

if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        # SQLite 默认不强制外键；不显式开启的话，模型声明的 ondelete=CASCADE / SET NULL
        # 不会生效，删除账号/仓库等父记录会留下孤儿行。
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """后台任务专用会话上下文。"""
    async with SessionLocal() as session:
        yield session
