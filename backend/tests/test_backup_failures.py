"""A failing PostgreSQL dump or compressor never becomes a listed backup."""

from __future__ import annotations

import asyncio
import gzip

import pytest

from app.services import backup


class FakeDump:
    def __init__(self, data=b"-- SQL fixture\n", returncode=0):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(data)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(b"secret connection detail")
        self.stderr.feed_eof()
        self.returncode = returncode
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture
def postgres_dump(monkeypatch, tmp_path):
    monkeypatch.setattr(backup.settings, "database_url", "postgresql+asyncpg://fixture:secret@localhost/qbot")
    monkeypatch.setattr(backup.settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(backup.shutil, "which", lambda _: "pg_dump")
    dump = FakeDump()

    async def spawn(*args, **kwargs):
        return dump

    monkeypatch.setattr(backup.asyncio, "create_subprocess_exec", spawn)
    return dump, tmp_path


async def test_failed_dump_removes_partial_file_and_hides_connection_details(postgres_dump):
    dump, folder = postgres_dump
    dump.returncode = 7
    with pytest.raises(RuntimeError, match="退出码 7") as result:
        await backup.backup_database()
    assert "secret" not in str(result.value)
    assert list(folder.iterdir()) == []


async def test_compression_failure_terminates_dump_and_removes_partial_file(postgres_dump, monkeypatch):
    dump, folder = postgres_dump
    dump.returncode = None

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backup.gzip, "open", fail)
    with pytest.raises(OSError, match="disk full"):
        await backup.backup_database()
    assert dump.killed
    assert list(folder.iterdir()) == []


async def test_empty_dump_is_rejected(postgres_dump):
    dump, folder = postgres_dump
    dump.stdout = asyncio.StreamReader()
    dump.stdout.feed_eof()
    with pytest.raises(RuntimeError, match="任何数据库内容"):
        await backup.backup_database()
    assert list(folder.iterdir()) == []


async def test_success_is_atomic_valid_gzip_and_listed(postgres_dump):
    _, folder = postgres_dump
    target = await backup.backup_database()
    assert list(folder.iterdir()) == [target]
    with gzip.open(target, "rb") as source:
        assert source.read() == b"-- SQL fixture\n"
    assert backup.list_backups()[0]["name"] == target.name
