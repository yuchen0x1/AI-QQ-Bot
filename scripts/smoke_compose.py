"""Build and exercise QBot on an isolated PostgreSQL/Redis Compose stack."""

from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import subprocess
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor


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
        env = {**os.environ, "QBOT_ENV_FILE": str(env_file), "HTTP_BIND": "127.0.0.1", "HTTP_PORT": "0"}
        # Prevent a host deployment's inherited values from shadowing the fixture.
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "REDIS_PASSWORD"):
            env.pop(key, None)
        command = ["docker", "compose", "--project-name", project, "--env-file", str(env_file)]

        def compose(*args, **options):
            return subprocess.run([*command, *args], cwd=ROOT, env=env, text=True, **options)

        try:
            compose("up", "--wait", "--wait-timeout", "180", "--build", check=True)
            port = compose("port", "nginx", "80", check=True, capture_output=True).stdout.strip()
            verify("http://" + port, password)
        except Exception:
            compose("ps")
            compose("logs", "--tail", "40")
            raise
        finally:
            compose("down", "--volumes", "--remove-orphans", "--rmi", "local", check=True)


if __name__ == "__main__":
    main()
