"""数据库备份与恢复辅助。"""

from __future__ import annotations

import asyncio
from contextlib import closing
import logging
import os
import re
import sqlite3
import shutil
import subprocess
import gzip
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger("qbot.backup")


def _backup_dir() -> Path:
    path = Path(settings.backup_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _sqlite_path(url: str) -> Path:
    """Extract a filesystem path from the SQLite SQLAlchemy URL.

    The project uses ``sqlite+aiosqlite:///C:/...`` on Windows and ordinary
    absolute paths on Unix.  Keep the existing URL compatibility while
    stripping query options that belong to the SQLite driver.
    """
    raw = url.split("///", 1)[-1].split("?", 1)[0]
    raw = unquote(raw)
    if raw.startswith("file:"):
        raw = raw[5:]
    if os.name == "nt" and re.match(r"^/[A-Za-z]:[\\/]", raw):
        raw = raw[1:]
    return Path(raw)


def _sqlite_online_backup(source: Path, target: Path) -> None:
    """Copy a live SQLite database using SQLite's online backup API.

    A byte-for-byte file copy can capture an inconsistent main/WAL pair while
    the application is writing.  ``Connection.backup`` coordinates with the
    source database and produces a transactionally consistent snapshot.  The
    temporary destination is atomically renamed only after the backup closes.
    """
    temporary = target.with_name(f".{target.name}.{os.getpid()}-{uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(str(source), timeout=30)) as source_db, closing(
            sqlite3.connect(str(temporary), timeout=30)
        ) as target_db:
            source_db.backup(target_db, pages=1000, sleep=0.05)
            target_db.commit()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


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


def _verify_gzip(path: Path) -> None:
    size = 0
    with gzip.open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
    if not size:
        raise RuntimeError("pg_dump 未返回任何数据库内容")


async def backup_database() -> Path:
    """备份数据库：SQLite 在线备份，PostgreSQL 调用 pg_dump。"""
    url = settings.database_url
    target_dir = _backup_dir()
    if url.startswith("sqlite"):
        source = _sqlite_path(url)
        if not source.exists():
            raise FileNotFoundError(f"SQLite 数据库文件不存在：{source}")
        target = target_dir / f"qbot-{_timestamp()}.db"
        await asyncio.to_thread(_sqlite_online_backup, source, target)
        logger.info("SQLite 备份完成：%s", target)
        return target

    pg = _pg_parts(url)
    if not shutil.which("pg_dump"):
        raise RuntimeError("未找到 pg_dump，无法备份 PostgreSQL（请安装 postgresql-client）")
    target = target_dir / f"qbot-{_timestamp()}-{uuid4().hex[:8]}.sql.gz"
    temporary = target.with_name(f".{target.name}.tmp")
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
    process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                 env={**os.environ, **env})
    stderr_task = asyncio.create_task(process.stderr.read()) if process.stderr is not None else None
    try:
        assert process.stdout is not None
        with gzip.open(temporary, "wb") as fh:
            while chunk := await process.stdout.read(1024 * 1024):
                fh.write(chunk)
        stderr = await stderr_task if stderr_task is not None else b""
        await process.wait()
        if process.returncode != 0:
            # stderr can contain database connection details; keep them out of API errors.
            logger.warning("pg_dump failed with exit status %s (%s stderr bytes)", process.returncode, len(stderr))
            raise RuntimeError(f"pg_dump 失败（退出码 {process.returncode}）")
        await asyncio.to_thread(_verify_gzip, temporary)
        os.replace(temporary, target)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        temporary.unlink(missing_ok=True)
    logger.info("PostgreSQL 备份完成：%s", target)
    return target


def list_backups(limit: int = 50) -> list[dict[str, object]]:
    folder = _backup_dir()
    files = sorted((p for p in folder.glob("qbot-*") if p.is_file() and not p.is_symlink()
                    and (p.name.endswith(".db") or p.name.endswith(".sql.gz"))),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "name": f.name,
            # Do not expose the server's absolute filesystem layout through a
            # management API.  The filename is sufficient for display and
            # preserves the historical response key for clients.
            "path": f.name,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in files
    ]


def prune_backups(keep: int = 14) -> int:
    if keep < 1:
        raise ValueError("至少保留一份备份")
    folder = _backup_dir()
    files = sorted((p for p in folder.glob("qbot-*") if p.is_file() and not p.is_symlink()
                    and (p.name.endswith(".db") or p.name.endswith(".sql.gz"))),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for stale in files[keep:]:
        stale.unlink(missing_ok=True)
        stale.with_name(stale.name + ".sha256").unlink(missing_ok=True)
        removed += 1
    return removed
