"""Host-owned, Unix-socket update supervisor. No shell or caller-supplied paths/URLs."""

from __future__ import annotations

import argparse
import ast
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import socketserver
import sqlite3
import stat
import struct
import subprocess
import tarfile
import threading
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

ACTIVE = {"queued", "running"}
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024
PHASES = {
    "queued": "已加入升级任务",
    "resolving": "读取正式版本信息",
    "downloading": "服务器正在下载升级包",
    "verifying": "校验下载文件",
    "extracting": "准备新版本文件",
    "dependencies": "安装新版本运行环境",
    "stopping": "正在准备重启",
    "backup": "备份现有数据库",
    "switching": "安装新版本",
    "checking": "启动并检查新版本",
    "committing": "恢复机器人与定时任务",
    "complete": "升级成功",
    "rolling_back": "正在恢复升级前的版本",
    "rolled_back": "升级未完成，已恢复原版本",
    "failed": "升级未完成，原版本继续运行",
    "attention": "升级服务需要检查，请查看服务器升级记录",
}


def version_tuple(version: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("仅支持正式版本号")
    return tuple(map(int, version.split(".")))


def source_version(folder: Path) -> str:
    tree = ast.parse((folder / "backend/app/core/version.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets
        ):
            value = ast.literal_eval(node.value)
            version_tuple(value)
            return value
    raise ValueError("无法读取版本信息")


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False), 0o600)


def sync_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_text(path: Path, value: str, mode: int) -> None:
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, mode)
    temp.replace(path)
    sync_directory(path.parent)


def below(base: Path, path: Path) -> Path:
    target = path.resolve()
    if not target.is_relative_to(base.resolve()) or target == base.resolve():
        raise ValueError("部署路径不在允许的目录中")
    return target


def allowed_url(url: str, hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in hosts
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
    )


class GithubRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(
            newurl,
            {"github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"},
        ):
            raise ValueError("下载地址重定向到非 GitHub 服务")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def release_asset(release: dict, repository: str, version: str) -> dict:
    tag = "v" + version
    if release.get("tag_name") != tag or release.get("draft") or release.get("prerelease"):
        raise ValueError("目标版本不是指定的正式发布")
    name = f"qbot-ai-{version}-native.tar.gz"
    matches = [a for a in release.get("assets", []) if a.get("name") == name]
    if len(matches) != 1:
        raise ValueError("该版本没有可自动安装的服务器升级包")
    asset = matches[0]
    if not isinstance(asset.get("id"), int) or asset["id"] <= 0:
        raise ValueError("升级包标识无效")
    expected = f"https://github.com/{repository}/releases/download/{tag}/{name}"
    if asset.get("browser_download_url") != expected or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", asset.get("digest", "")
    ):
        raise ValueError("升级包来源或 SHA-256 信息不符合要求")
    if not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= MAX_ARCHIVE:
        raise ValueError("升级包大小不符合要求")
    return asset


def unpack(archive: Path, destination: Path, version: str) -> None:
    prefix = "qbot-ai-" + version
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > 20000 or sum(m.size for m in members) > MAX_UNPACKED:
            raise ValueError("升级包展开后过大")
        seen = set()
        checked = []
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (
                not parts
                or parts[0] != prefix
                or ".." in parts
                or "\\" in member.name
                or not (member.isfile() or member.isdir())
                or member.size < 0
            ):
                raise ValueError("升级包含有不安全路径或链接")
            relative = Path(*parts[1:])
            key = relative.as_posix().casefold()
            if key in seen:
                raise ValueError("升级包含有重复路径")
            seen.add(key)
            if len(parts) > 1 and parts[1] not in {"backend", "frontend", "qbot-update.json"}:
                raise ValueError("升级包包含不允许的目录")
            if any(p in {".env", "data", "backups", ".venv", "node_modules", "__pycache__"} for p in parts):
                raise ValueError("升级包混入运行数据")
            checked.append((member, relative))
        destination.mkdir(mode=0o755, parents=False)
        for member, relative in checked:
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as src, target.open("xb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, 0o644)
    manifest = json.loads((destination / "qbot-update.json").read_text(encoding="utf-8"))
    if (
        manifest.get("version") != version
        or manifest.get("format") != "native-systemd-v1"
        or manifest.get("maintenance_protocol") != 1
        or manifest.get("python") != "3.12"
    ):
        raise ValueError("升级包格式不兼容")
    if source_version(destination) != version or not (destination / "frontend/dist/index.html").is_file():
        raise ValueError("升级包版本或前端文件不完整")
    if json.loads((destination / "frontend/package.json").read_text())["version"] != version:
        raise ValueError("前后端版本不一致")


def backup_database(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise ValueError("待备份数据库不存在")
    temp = destination.with_suffix(".tmp")
    with (
        closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(temp)) as out,
    ):
        if src.execute("pragma integrity_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性检查未通过")
        src.backup(out)
    os.chmod(temp, 0o600)
    temp.replace(destination)
    sync_directory(destination.parent)


class Updater:
    def __init__(self, config: dict):
        self.config = config
        self.root = Path(config["root_dir"])
        self.releases = self.root / "releases"
        self.current = self.root / "current"
        self.state_dir = Path(config["state_dir"])
        self.jobs = self.state_dir / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.pointer = self.state_dir / "current.json"
        self.gate = Path(config.get("gate_dir", config["run_dir"])) / "maintenance"
        self.lock = threading.RLock()
        self.opener = build_opener(GithubRedirects())

    def current_job(self) -> dict | None:
        if not self.pointer.exists():
            return None
        job_id = str(UUID(json.loads(self.pointer.read_text())["id"]))
        return json.loads((self.jobs / (job_id + ".json")).read_text(encoding="utf-8"))

    def public_state(self) -> dict:
        with self.lock:
            job = self.current_job()
            keys = {
                "id",
                "version",
                "previous_version",
                "status",
                "phase",
                "message",
                "progress",
                "started_at",
                "updated_at",
                "error",
            }
            return {"mode": "native_systemd", "job": {k: v for k, v in job.items() if k in keys} if job else None}

    def save(self, job: dict, phase: str, progress: int, **values) -> None:
        with self.lock:
            job.update(phase=phase, message=PHASES[phase], progress=progress, updated_at=time.time(), **values)
            atomic_json(self.jobs / (job["id"] + ".json"), job)

    def start(self, version: str, request_id: str, *, launch=True) -> dict:
        version_tuple(version)
        job_id = str(UUID(request_id))
        with self.lock:
            existing = self.jobs / (job_id + ".json")
            if existing.exists():
                if json.loads(existing.read_text(encoding="utf-8"))["version"] != version:
                    raise ValueError("同一个请求不能用于不同版本")
                return self.public_state()
            active = self.current_job()
            if active and active["status"] in ACTIVE:
                raise ValueError("已有升级任务正在进行，请勿重复点击")
            if self.gate.exists() or active and active["status"] == "attention":
                raise ValueError("上次升级仍需检查，请先恢复服务再发起新任务")
            previous = below(self.releases, self.current.resolve())
            previous_version = source_version(previous)
            if version_tuple(version) <= version_tuple(previous_version):
                raise ValueError("目标版本必须高于当前版本")
            if shutil.disk_usage(self.root).free < 2 * MAX_UNPACKED:
                raise ValueError("磁盘空间不足，至少需要 2 GB 可用空间")
            job = {
                "id": job_id,
                "version": version,
                "previous_version": previous_version,
                "previous_release": str(previous),
                "new_release": str(self.releases / ("v" + version + "-" + job_id)),
                "backup": str(Path(self.config["backup_dir"]) / ("upgrade-" + job_id + ".db")),
                "status": "queued",
                "started_at": time.time(),
                "error": None,
            }
            self.save(job, "queued", 0)
            atomic_json(self.pointer, {"id": job_id})
            if launch:
                threading.Thread(target=self.install, args=(job,), daemon=True).start()
            return self.public_state()

    def fetch_release(self, version: str) -> dict:
        repository = self.config["repository"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("升级源配置无效")
        request = Request(
            f"https://api.github.com/repos/{repository}/releases/latest",
            headers={"User-Agent": "QBot-Native-Updater/1", "Accept": "application/vnd.github+json"},
        )
        with self.opener.open(request, timeout=35) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("版本信息过大")
        return release_asset(json.loads(raw), repository, version)

    def download(self, job: dict, asset: dict, path: Path) -> None:
        digest = hashlib.sha256()
        total = 0
        deadline = time.monotonic() + 300
        request = Request(
            f"https://api.github.com/repos/{self.config['repository']}/releases/assets/{asset['id']}",
            headers={"User-Agent": "QBot-Native-Updater/1", "Accept": "application/octet-stream"},
        )
        with self.opener.open(request, timeout=35) as response, path.open("xb") as out:
            while chunk := response.read(256 * 1024):
                total += len(chunk)
                if total > asset["size"] or time.monotonic() > deadline:
                    raise ValueError("下载大小或等待时间超过限制")
                digest.update(chunk)
                out.write(chunk)
                self.save(job, "downloading", 10 + int(25 * total / asset["size"]))
        self.save(job, "verifying", 36)
        if total != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
            raise ValueError("下载文件 SHA-256 校验不通过")

    def command(self, job: dict, argv: list[str], timeout=90) -> None:
        with (self.jobs / (job["id"] + ".log")).open("ab") as log:
            subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=True,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            )

    def service(self, job: dict, action: str) -> None:
        self.command(job, ["/usr/bin/systemctl", action, self.config["service"]])

    def build_environment(self, job: dict, folder: Path) -> None:
        import pwd

        identity = pwd.getpwnam(self.config["build_user"])
        for directory, dirs, files in os.walk(folder, followlinks=False):
            for path in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
                os.chown(path, identity.pw_uid, identity.pw_gid, follow_symlinks=False)
        argv = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--expand-environment=no",
            "--unit=qbot-build-" + job["id"],
            "--service-type=exec",
            "--uid=" + self.config["build_user"],
            "--gid=" + self.config["build_user"],
            "--property=ProtectSystem=strict",
            "--property=ProtectHome=yes",
            "--property=PrivateTmp=yes",
            "--property=NoNewPrivileges=yes",
            "--property=MemoryMax=768M",
            "--property=CPUQuota=100%",
            "--property=RuntimeMaxSec=600",
            "--property=ReadWritePaths=" + str(folder),
            "/usr/bin/python3",
            str(Path(__file__).with_name("build_environment.py")),
            str(folder),
            self.config["python"],
        ]
        self.command(job, argv, timeout=630)
        # The transient unit has exited, including its children, before files become host-owned.
        for directory, dirs, files in os.walk(folder, followlinks=False):
            for path in [Path(directory), *(Path(directory) / name for name in dirs + files)]:
                if not (stat.S_ISREG(path.lstat().st_mode) or path.is_dir() or path.is_symlink()):
                    raise ValueError("运行环境包含不支持的文件类型")
                os.chown(path, 0, 0, follow_symlinks=False)
                if not path.is_symlink():
                    os.chmod(path, 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
                    if path.is_file():
                        with path.open("rb") as stream:
                            os.fsync(stream.fileno())
            sync_directory(Path(directory))

    def switch(self, destination: Path) -> None:
        target = below(self.releases, destination)
        if not target.is_dir():
            raise ValueError("版本目录不存在")
        link = self.root / "current.next"
        link.unlink(missing_ok=True)
        link.symlink_to(target, target_is_directory=True)
        link.replace(self.current)
        sync_directory(self.root)

    def healthy(self, version: str, *, deferred: bool | None = None, timeout=100) -> bool:
        import urllib.request

        until = time.monotonic() + timeout
        while time.monotonic() < until:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/api/system/health", timeout=3) as response:
                    data = json.loads(response.read(8192))
                if (
                    data.get("database")
                    and data.get("version") == version
                    and (deferred is None or data.get("services_deferred") is deferred)
                ):
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def remove_gate(self, job: dict) -> None:
        if self.gate.exists():
            if self.gate.read_text() != job["id"]:
                raise ValueError("维护状态与当前任务不一致")
            self.gate.unlink()
            sync_directory(self.gate.parent)

    def rollback(self, job: dict) -> None:
        self.save(job, "rolling_back", 85)
        self.service(job, "stop")
        backup = below(Path(self.config["backup_dir"]), Path(job["backup"]))
        if backup.exists():
            database = Path(self.config["database"])
            failed = backup.with_name("failed-" + job["id"] + ".db")
            try:
                backup_database(database, failed)
            except Exception:
                shutil.copyfile(database, failed)
            restored = backup.with_name("restore-" + job["id"] + ".db")
            backup_database(backup, restored)
            owner = database.stat()
            if hasattr(os, "chown"):
                os.chown(restored, owner.st_uid, owner.st_gid)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(database) + suffix)
                if sidecar.exists():
                    shutil.move(str(sidecar), str(failed) + suffix)
            restored.replace(database)
        elif self.current.resolve() != Path(job["previous_release"]).resolve():
            raise ValueError("缺少可恢复的数据库备份")
        self.switch(Path(job["previous_release"]))
        self.remove_gate(job)
        self.service(job, "start")
        if not self.healthy(job["previous_version"]):
            raise ValueError("原版本恢复后健康检查未通过")
        self.save(job, "rolled_back", 100, status="rolled_back")

    def install(self, job: dict) -> None:
        try:
            self.save(job, "resolving", 5, status="running")
            asset = self.fetch_release(job["version"])
            archive = self.jobs / (job["id"] + ".tar.gz")
            self.save(job, "downloading", 10)
            self.download(job, asset, archive)
            folder = below(self.releases, Path(job["new_release"]))
            self.save(job, "extracting", 40)
            unpack(archive, folder, job["version"])
            self.save(job, "dependencies", 45)
            self.build_environment(job, folder)
            self.save(job, "stopping", 65)
            atomic_text(self.gate, job["id"], 0o644)
            self.service(job, "stop")
            self.save(job, "backup", 70)
            backup_database(Path(self.config["database"]), Path(job["backup"]))
            self.save(job, "switching", 78)
            self.switch(folder)
            self.service(job, "start")
            self.save(job, "checking", 86)
            if not self.healthy(job["version"], deferred=True):
                raise ValueError("新版本启动检查失败")
            # Commit point: only now may the app accept writes and start outbound jobs.
            self.save(job, "committing", 96)
            self.remove_gate(job)
            if not self.healthy(job["version"], deferred=False, timeout=45):
                self.save(
                    job,
                    "attention",
                    100,
                    status="attention",
                    error="版本已安装，服务恢复需要检查；未回退已恢复写入的数据",
                )
                return
            self.save(job, "complete", 100, status="succeeded")
        except Exception as exc:
            # Do not expose subprocess logs or HTTP request details through the web UI.
            reason = str(exc)[:200] if isinstance(exc, ValueError) else f"升级阶段 {job['phase']} 未完成"
            self.save(job, job["phase"], job["progress"], error=reason)
            try:
                if self.gate.exists():
                    self.rollback(job)
                elif job["phase"] == "committing":
                    self.save(job, "attention", 100, status="attention", error="版本已切换，请检查服务恢复状态")
                else:
                    self.save(job, "failed", 100, status="failed")
            except Exception:
                self.save(job, "attention", 100, status="attention", error="恢复过程需要检查，已保留备份和升级记录")

    def recover(self) -> None:
        job = self.current_job()
        if not job or job["status"] not in ACTIVE:
            return
        try:
            if self.gate.exists():
                self.rollback(job)
            elif job["phase"] == "committing":
                if self.healthy(job["version"], deferred=False):
                    self.save(job, "complete", 100, status="succeeded")
                else:
                    self.save(job, "attention", 100, status="attention", error="重启后需检查服务状态，未覆盖当前数据")
            else:
                self.save(job, "failed", 100, status="failed", error="升级准备被中断，原版本未切换")
        except Exception:
            self.save(job, "attention", 100, status="attention", error="升级恢复需要检查，已保留全部数据")


def main() -> None:
    import fcntl
    import pwd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/qbot/updater.json")
    args = parser.parse_args()
    config_file = Path(args.config)
    if os.geteuid() != 0 or config_file.stat().st_uid != 0 or config_file.stat().st_mode & 0o022:
        parser.error("升级配置必须由 root 管理，且不允许其他用户写入")
    os.umask(0o077)
    config = json.loads(config_file.read_text())
    if config["service"] != "qbot.service":
        parser.error("此升级服务仅管理 qbot.service")
    backup_dir = Path(config["backup_dir"])
    if backup_dir.is_symlink() or backup_dir.stat().st_uid != 0 or backup_dir.stat().st_mode & 0o077:
        parser.error("升级备份目录必须由 root 独占，不能使用应用用户可写的目录")
    updater = Updater(config)
    Path(config["run_dir"]).mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(config["run_dir"], 0o755)
    lock = (updater.state_dir / "supervisor.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    updater.recover()
    socket_path = Path(config["run_dir"]) / "control.sock"
    socket_path.unlink(missing_ok=True)
    app_uid = pwd.getpwnam(config["app_user"]).pw_uid

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body):
            raw = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def permitted(self):
            uid = struct.unpack("3i", self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
            if uid not in (0, app_uid) or self.path != "/install":
                self.reply(403, {"detail": "请求不被允许"})
                return False
            return True

        def do_GET(self):
            if self.permitted():
                self.reply(200, updater.public_state())

        def do_POST(self):
            if not self.permitted():
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("无效请求大小")
                body = json.loads(self.rfile.read(size))
                if set(body) != {"version", "request_id"}:
                    raise ValueError("升级请求仅接受版本号和请求标识")
                self.reply(202, updater.start(body["version"], body["request_id"]))
            except (ValueError, TypeError, KeyError) as exc:
                self.reply(409, {"detail": str(exc)[:200]})

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    with Server(str(socket_path), Handler) as server:
        os.chown(socket_path, 0, pwd.getpwnam(config["app_user"]).pw_gid)
        os.chmod(socket_path, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    main()
