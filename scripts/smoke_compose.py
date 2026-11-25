"""Build and exercise QBot on an isolated PostgreSQL/Redis Compose stack."""

import json
import os
import secrets
import subprocess
import time
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def verify(base_url: str, password: str) -> None:
    browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        req = Request(base_url + path, data=body, headers={"Content-Type": "application/json"})
        with browser.open(req, timeout=15) as response:
            return response.read()

    if b'id="app"' not in request("/"):
        raise RuntimeError("Nginx did not serve the management frontend")
    health = json.loads(request("/api/system/health"))
    if health["status"] != "ok" or not health["database"] or health["services_deferred"]:
        raise RuntimeError("QBot or PostgreSQL is not ready")
    try:
        request("/api/auth/me")
    except HTTPError as exc:
        if exc.code != 401:
            raise
    else:
        raise RuntimeError("Unauthenticated request unexpectedly succeeded")
    request("/api/auth/login", {"username": "qbot-smoke", "password": password})
    if json.loads(request("/api/auth/me"))["username"] != "qbot-smoke":
        raise RuntimeError("Login cookie did not authenticate through Nginx")
    if not json.loads(request("/api/system/info"))["redis_enabled"]:
        raise RuntimeError("Redis is disabled")
    print(f"Compose smoke passed (QBot {health['version']})", flush=True)


def main() -> None:
    project = "qbot-smoke-" + secrets.token_hex(6)
    password = secrets.token_hex(24)
    with TemporaryDirectory(prefix="qbot-compose-") as temp:
        env_file = Path(temp) / "smoke.env"
        env_file.write_text(
            f"ENV=development\nHTTP_BIND=127.0.0.1\nHTTP_PORT=0\n"
            f"ADMIN_USERNAME=qbot-smoke\nADMIN_PASSWORD={password}\n"
            f"SECRET_KEY={secrets.token_hex(32)}\n"
            f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nREDIS_PASSWORD={secrets.token_hex(24)}\n",
            encoding="utf-8",
        )
        env = {**os.environ, "QBOT_ENV_FILE": str(env_file), "COMPOSE_PROJECT_NAME": project,
               "HTTP_BIND": "127.0.0.1", "HTTP_PORT": "0"}
        # Prevent a host deployment's inherited values from shadowing the fixture.
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "REDIS_PASSWORD"):
            env.pop(key, None)
        command = ["docker", "compose", "--project-name", project, "--env-file", str(env_file)]

        def compose(*args, **options):
            return subprocess.run([*command, *args], check=options.pop("check", False),
                                  cwd=ROOT, env=env, text=True, **options)

        try:
            compose("up", "--wait", "--wait-timeout", "180", "--build", check=True)
            port = compose("port", "nginx", "80", check=True, capture_output=True).stdout.strip()
            base_url = "http://" + port
            verify(base_url, password)
            # Exercise the actual shell backup/restore path against isolated PostgreSQL.
            def sql(statement):
                return compose("exec", "-T", "postgres", "sh", "-ec",
                               'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"',
                               "sh", statement, check=True, capture_output=True).stdout.strip()

            sql("CREATE TABLE qbot_restore_probe (id integer PRIMARY KEY); INSERT INTO qbot_restore_probe VALUES (1)")
            previous = set((ROOT / "backups").glob("qbot-*.sql.gz"))
            subprocess.run(["bash", "backup.sh"], cwd=ROOT, env=env, check=True)
            archives = set((ROOT / "backups").glob("qbot-*.sql.gz")) - previous
            if len(archives) != 1:
                raise RuntimeError("Backup did not atomically publish one archive")
            archive = next(iter(archives))
            sql("INSERT INTO qbot_restore_probe VALUES (2)")
            subprocess.run(["bash", "restore.sh", "--verify-only", str(archive)], cwd=ROOT, env=env, check=True)
            if sql("SELECT count(*) FROM qbot_restore_probe") != "2":
                raise RuntimeError("Rehearsal modified the live database")
            subprocess.run(["bash", "restore.sh", str(archive)], cwd=ROOT, env=env,
                           input="RESTORE\n", text=True, check=True)
            if sql("SELECT count(*) FROM qbot_restore_probe") != "1":
                raise RuntimeError("Restore did not recover the snapshot data")
            deadline = time.monotonic() + 90
            while True:
                try:
                    verify(base_url, password)
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(2)
            print("PostgreSQL backup, isolated rehearsal, maintenance restore and login recovery passed", flush=True)
        except Exception:
            compose("ps")
            compose("logs", "--tail", "40")
            raise
        finally:
            compose("down", "--volumes", "--remove-orphans", "--rmi", "local", check=True)


if __name__ == "__main__":
    main()
