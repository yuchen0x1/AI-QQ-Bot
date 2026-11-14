"""Install the narrow host updater once on an existing /opt/qbot native deployment."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import UUID


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this setup as root")
    root = Path("/opt/qbot")
    current = (root / "current").resolve()
    if not current.is_relative_to(root / "releases") or not (current / "backend/app/main.py").is_file():
        raise SystemExit("Expected an existing /opt/qbot native installation")
    repository = Path(__file__).resolve().parents[2]
    pointer = Path("/var/lib/qbot-updater/current.json")
    if pointer.exists():
        ident = str(UUID(json.loads(pointer.read_text())["id"]))
        state = json.loads((pointer.parent / "jobs" / (ident + ".json")).read_text())
        if state["status"] in {"queued", "running", "attention"}:
            raise SystemExit("Resolve the existing upgrade task before installing the supervisor")
    for path in [
        "/var/lib/qbot-updater",
        "/var/lib/qbot-updater/jobs",
        "/var/lib/qbot-updater/backups",
        "/var/lib/qbot-updater-status",
        "/etc/qbot",
        "/usr/local/lib/qbot-updater",
    ]:
        Path(path).mkdir(parents=True, exist_ok=True)
    os.chmod("/var/lib/qbot-updater", 0o700)
    os.chmod("/var/lib/qbot-updater/backups", 0o700)
    os.chmod("/var/lib/qbot-updater-status", 0o755)
    subprocess.run(
        ["/usr/bin/getent", "passwd", "qbot-build"], stdout=subprocess.DEVNULL, check=False
    ).returncode == 0 or subprocess.run(
        ["/usr/sbin/useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "qbot-build"], check=True
    )
    for name in ["daemon.py", "build_environment.py"]:
        target = Path("/usr/local/lib/qbot-updater") / name
        shutil.copyfile(Path(__file__).with_name(name), target)
        os.chmod(target, 0o644)
    env = Path("/etc/qbot/qbot.env")
    database = Path("/var/lib/qbot/qbot.db")
    database_lines = [
        line.split("=", 1)[1].strip().strip("\"'")
        for line in env.read_text().splitlines()
        if line.startswith("DATABASE_URL=")
    ]
    if database_lines != ["sqlite+aiosqlite:////var/lib/qbot/qbot.db"] or not database.is_file():
        raise SystemExit("This updater requires the documented native SQLite deployment")
    snapshot = Path("/etc/qbot/qbot.env.before-updater")
    if not snapshot.exists():
        shutil.copy2(env, snapshot)
        os.chmod(snapshot, 0o600)
    lines = [
        line
        for line in env.read_text().splitlines()
        if not line.startswith(("UPDATE_SOCKET=", "UPDATE_MAINTENANCE_FILE="))
    ]
    lines += [
        "UPDATE_SOCKET=/run/qbot-updater/control.sock",
        "UPDATE_MAINTENANCE_FILE=/var/lib/qbot-updater-status/maintenance",
    ]
    env.write_text("\n".join(lines) + "\n")
    os.chmod(env, 0o640)
    legacy_venv = current / ".venv"
    if not legacy_venv.exists():
        legacy_venv.symlink_to(root / "venv", target_is_directory=True)
    config = {
        "repository": "yuchen0x1/AI-QQ-Bot",
        "root_dir": str(root),
        "database": "/var/lib/qbot/qbot.db",
        "backup_dir": "/var/lib/qbot-updater/backups",
        "state_dir": "/var/lib/qbot-updater",
        "run_dir": "/run/qbot-updater",
        "gate_dir": "/var/lib/qbot-updater-status",
        "python": "/opt/qbot/runtime/python/bin/python3",
        "service": "qbot.service",
        "app_user": "qbot",
        "build_user": "qbot-build",
        "download_mirrors": [],
        "pip_index_url": "",
    }
    destination = Path("/etc/qbot/updater.json")
    if destination.exists():
        config = {
            **config,
            **json.loads(destination.read_text()),
            "gate_dir": "/var/lib/qbot-updater-status",
            "backup_dir": "/var/lib/qbot-updater/backups",
        }
    destination.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(destination, 0o600)
    nginx = Path("/etc/nginx/sites-available/qbot")
    marker = "if (-f /var/lib/qbot-updater-status/maintenance) { return 503; }"
    site = nginx.read_text()
    if marker not in site:
        if not nginx.with_name("qbot.before-updater").exists():
            shutil.copy2(nginx, nginx.with_name("qbot.before-updater"))
        previous_marker = "if (-f /run/qbot-updater/maintenance) { return 503; }"
        if previous_marker in site:
            site = site.replace(previous_marker, marker)
        else:
            for directive in (
                "    location = /api/auth/login {",
                "    location /api/ws/ {",
                "    location /api/ {",
                "    location = /webhook {",
            ):
                if directive not in site:
                    raise SystemExit("Nginx site does not match the supported native layout")
                site = site.replace(directive, directive + "\n        " + marker)
        nginx.write_text(site)
    subprocess.run(["/usr/sbin/nginx", "-t"], check=True)
    for service in ("qbot.service", "qbot-updater.service"):
        shutil.copyfile(repository / "scripts/systemd" / service, Path("/etc/systemd/system") / service)
    subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True)
    subprocess.run(["/usr/bin/systemctl", "reload", "nginx"], check=True)
    subprocess.run(["/usr/bin/systemctl", "enable", "qbot-updater"], check=True)
    subprocess.run(["/usr/bin/systemctl", "restart", "qbot-updater"], check=True)
    print("Updater installed. Restart qbot after deploying the upgrade entry API and UI.")


if __name__ == "__main__":
    main()
