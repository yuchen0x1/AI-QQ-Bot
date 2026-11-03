"""数据库备份与恢复辅助。"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import settings

logger = logging.getLogger("qbot.backup")


def _backup_dir() -> Path:
    path = Path(settings.backup_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _pg_parts(url: str) -> dict[str, str]:
    # 支持 postgresql+asyncpg://user:pass@host:port/db
    cleaned = url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")
    parsed = urlparse(cleaned)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "dbname": (parsed.path or "/").lstrip("/"),
    }


async def backup_database() -> Path:
    """备份数据库：SQLite 直接复制文件，PostgreSQL 调用 pg_dump。"""
    url = settings.database_url
    target_dir = _backup_dir()
    if url.startswith("sqlite"):
        path = url.split("///")[-1]
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(f"SQLite 数据库文件不存在：{source}")
        target = target_dir / f"qbot-{_timestamp()}.db"
        shutil.copy2(source, target)
        logger.info("SQLite 备份完成：%s", target)
        return target

    pg = _pg_parts(url)
    if not shutil.which("pg_dump"):
        raise RuntimeError("未找到 pg_dump，无法备份 PostgreSQL（请安装 postgresql-client）")
    target = target_dir / f"qbot-{_timestamp()}.sql.gz"
    env = {"PGPASSWORD": pg["password"]}
    cmd = [
        "pg_dump",
        "-h",
        pg["host"],
        "-p",
        pg["port"],
        "-U",
        pg["user"],
        "-d",
        pg["dbname"],
        "--no-owner",
        "--clean",
        "--if-exists",
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**__import__("os").environ, **env}
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"pg_dump 失败：{stderr.decode('utf-8', 'ignore')[:500]}")
    import gzip

    with gzip.open(target, "wb") as fh:
        fh.write(stdout)
    logger.info("PostgreSQL 备份完成：%s", target)
    return target


def list_backups(limit: int = 50) -> list[dict[str, object]]:
    folder = _backup_dir()
    files = sorted(folder.glob("qbot-*"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "name": f.name,
            "path": str(f),
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in files
    ]


def prune_backups(keep: int = 14) -> int:
    folder = _backup_dir()
    files = sorted(folder.glob("qbot-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for stale in files[keep:]:
        stale.unlink(missing_ok=True)
        removed += 1
    return removed
