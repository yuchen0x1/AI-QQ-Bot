"""Upgrade request permissions, archive trust boundaries, deferral and rollback."""

import asyncio
from contextlib import closing
import io
from pathlib import Path
import runpy
import sqlite3
import tarfile
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.services import update_installer, runtime_start

host = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/updater/daemon.py"))


def release(version="2.0.0"):
    name = f"qbot-ai-{version}-native.tar.gz"
    return {
        "tag_name": "v" + version,
        "assets": [
            {
                "name": name,
                "id": 123,
                "size": 100,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": f"https://github.com/yuchen0x1/AI-QQ-Bot/releases/download/v{version}/{name}",
            }
        ],
    }


@pytest.mark.parametrize("change", ["url", "digest", "prerelease", "version", "size"])
def test_native_asset_rejects_untrusted_or_invalid_metadata(change):
    data = release()
    if change == "url":
        data["assets"][0]["browser_download_url"] = "https://attacker.invalid/update.tar.gz"
    if change == "digest":
        data["assets"][0]["digest"] = ""
    if change == "prerelease":
        data["prerelease"] = True
    if change == "version":
        data["tag_name"] = "v1.0.0"
    if change == "size":
        data["assets"][0]["size"] = host["MAX_ARCHIVE"] + 1
    with pytest.raises(ValueError):
        host["release_asset"](data, "yuchen0x1/AI-QQ-Bot", "2.0.0")


@pytest.mark.parametrize(
    "name,link",
    [
        ("qbot-ai-2.0.0/../../escaped", False),
        ("/outside", False),
        ("qbot-ai-2.0.0/backend/link", True),
        ("qbot-ai-2.0.0/data/qbot.db", False),
    ],
)
def test_archive_refuses_traversal_links_and_runtime_data(tmp_path, name, link):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        if link:
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
        else:
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    target = tmp_path / "output"
    with pytest.raises(ValueError):
        host["unpack"](archive, target, "2.0.0")
    assert not target.exists()
    assert not (tmp_path / "escaped").exists()


def test_asset_and_redirect_allowlist_accept_only_pinned_sources():
    assert host["release_asset"](release(), "yuchen0x1/AI-QQ-Bot", "2.0.0")["size"] == 100
    allowed = host["allowed_url"]
    assert allowed("https://release-assets.githubusercontent.com/file", {"release-assets.githubusercontent.com"})
    for url in [
        "http://github.com/file",
        "https://github.com.attacker.invalid/file",
        "https://x:secret@github.com/file",
        "https://github.com:444/file",
    ]:
        assert not allowed(url, {"github.com"})


@pytest.fixture
def updater(tmp_path):
    root = tmp_path / "app"
    old = root / "releases/old"
    (old / "backend/app/core").mkdir(parents=True)
    (old / "backend/app/core/version.py").write_text('APP_VERSION = "1.0.0"')
    (root / "current").mkdir()  # Windows fixture avoids requiring symlink privileges.
    state, backups, run = tmp_path / "state", tmp_path / "backups", tmp_path / "run"
    backups.mkdir()
    run.mkdir()
    database = tmp_path / "qbot.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("create table retained(value text)")
        db.execute("insert into retained values('before')")
        db.commit()
    cfg = {
        "root_dir": str(root),
        "state_dir": str(state),
        "backup_dir": str(backups),
        "run_dir": str(run),
        "database": str(database),
    }
    obj = host["Updater"](cfg)
    return obj, old, database


def test_rollback_restores_database_and_original_release(updater, monkeypatch):
    obj, old, database = updater
    ident = str(uuid4())
    backup = Path(obj.config["backup_dir"]) / ("upgrade-" + ident + ".db")
    host["backup_database"](database, backup)
    with closing(sqlite3.connect(database)) as db:
        db.execute("update retained set value='after-migration'")
        db.commit()
    obj.gate.write_text(ident)
    job = {
        "id": ident,
        "version": "2.0.0",
        "previous_version": "1.0.0",
        "previous_release": str(old),
        "backup": str(backup),
        "status": "running",
    }
    actions = []
    monkeypatch.setattr(obj, "service", lambda job, action: actions.append(action))
    monkeypatch.setattr(obj, "switch", lambda target: actions.append(target))
    monkeypatch.setattr(obj, "healthy", lambda version, **kw: version == "1.0.0")
    obj.rollback(job)
    assert actions == ["stop", old, "start"]
    assert not obj.gate.exists() and job["status"] == "rolled_back"
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("select value from retained").fetchone()[0] == "before"
    with closing(sqlite3.connect(backup.with_name("failed-" + ident + ".db"))) as db:
        assert db.execute("select value from retained").fetchone()[0] == "after-migration"


def test_recovery_never_restores_data_after_commit_point(updater, monkeypatch):
    obj, old, database = updater
    ident = str(uuid4())
    job = {"id": ident, "version": "2.0.0", "status": "running", "phase": "committing", "progress": 96}
    obj.save(job, "committing", 96)
    host["atomic_json"](obj.pointer, {"id": ident})
    monkeypatch.setattr(obj, "healthy", lambda *a, **kw: True)
    monkeypatch.setattr(obj, "rollback", lambda *a: pytest.fail("Committed writes must not be reverted"))
    obj.recover()
    assert obj.current_job()["status"] == "succeeded"


def test_host_requests_deduplicate_and_serialize_upgrade_jobs(updater, monkeypatch):
    obj, old, database = updater
    monkeypatch.setattr(obj, "current", old)
    request_id = str(uuid4())
    first = obj.start("2.0.0", request_id, launch=False)
    assert obj.start("2.0.0", request_id, launch=False) == first
    assert len(list(obj.jobs.glob("*.json"))) == 1
    with pytest.raises(ValueError, match="已有升级任务"):
        obj.start("3.0.0", str(uuid4()), launch=False)
    with pytest.raises(ValueError, match="不同版本"):
        obj.start("3.0.0", request_id, launch=False)


async def test_runtime_waits_for_upgrade_gate_before_any_outbound_work(tmp_path, monkeypatch):
    gate = tmp_path / "maintenance"
    gate.write_text("job")
    monkeypatch.setattr(settings, "update_maintenance_file", str(gate))
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    calls = []

    async def scheduler():
        calls.append("scheduler")

    async def accounts():
        calls.append("accounts")

    monkeypatch.setattr(runtime_start.scheduler_service, "start", scheduler)
    monkeypatch.setattr(runtime_start.account_manager, "boot_auto_start", accounts)
    task = asyncio.create_task(runtime_start.start_runtime())
    await asyncio.sleep(0.02)
    assert not calls and runtime_start.services_deferred
    gate.unlink()
    await asyncio.wait_for(task, 2)
    assert calls == ["scheduler", "accounts"] and not runtime_start.services_deferred


async def test_upgrade_api_is_authenticated_idempotent_bridge_and_rejects_paths(client, admin_headers, monkeypatch):
    sent = []

    async def rpc(method="GET", payload=None):
        sent.append((method, payload))
        return {"job": {"id": str(payload["request_id"]), "status": "queued"}}

    monkeypatch.setattr(update_installer, "installer_rpc", rpc)
    payload = {"version": "2.0.0", "request_id": str(uuid4())}
    response = await client.post("/api/system/update/install", headers=admin_headers, json=payload)
    assert response.status_code == 202
    assert sent == [("POST", payload)]
    bad = {**payload, "url": "https://attacker.invalid/code"}
    assert (await client.post("/api/system/update/install", headers=admin_headers, json=bad)).status_code == 422
    # A fresh HTTP client has no admin cookie from the shared fixture.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client._transport.app), base_url="http://test"
    ) as anon:
        assert (await anon.post("/api/system/update/install", json=payload)).status_code == 401


async def test_missing_host_installer_is_reported_truthfully(monkeypatch):
    monkeypatch.setattr(settings, "update_socket", "")
    state = await update_installer.installer_state()
    assert not state["available"] and state["job"] is None
