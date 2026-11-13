"""Narrow, shell-free interface to Tencent's official Agent Mail CLI."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlparse

from app.core.config import BASE_DIR, settings
from app.core.logging import mask_text

_login: dict = {"state": "idle", "url": "", "error": ""}
_login_task: asyncio.Task | None = None
_login_process: asyncio.subprocess.Process | None = None


def executable() -> str | None:
    if settings.agently_cli_path:
        candidate = settings.agently_cli_path
    else:
        local = BASE_DIR / ".downloads/agently-runtime/node_modules/@tencent-qqmail/agently-cli-win32-x64/bin/agently-cli.exe"
        candidate = str(local) if os.name == "nt" and local.is_file() else shutil.which("agently-cli")
    if not candidate or not Path(candidate).is_file():
        return None
    if os.name == "nt" and Path(candidate).suffix.lower() in {".cmd", ".ps1", ".bat"}:
        # npm's Windows shim is a script. Resolve its native package rather than launching a shell.
        prefix = Path(candidate).parent / "node_modules/@tencent-qqmail"
        for arch in ("x64", "arm64"):
            for parent in (prefix, prefix / "agently-cli/node_modules/@tencent-qqmail"):
                binary = parent / f"agently-cli-win32-{arch}/bin/agently-cli.exe"
                if binary.is_file():
                    return str(binary)
        return None
    return candidate


def cli_env() -> dict[str, str]:
    # Keep this app's credential store separate from other agents and out of server packages.
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"}}
    config = Path(settings.data_dir) / "agent-mail"
    config.mkdir(parents=True, exist_ok=True)
    env.update(AGENTLY_CLI_CONFIG_DIR=str(config), AGENTLY_CLI_NO_UPDATE_NOTIFIER="1", AGENTLY_DISABLE_TELEMETRY="1")
    return env


async def run_cli(*args: str, cwd: str | None = None, timeout: int = 35) -> dict:
    command = executable()
    if not command:
        raise ValueError("未安装 Agent Mail 发信工具；Docker 镜像已内置，本机可按操作文档安装")
    process = await asyncio.create_subprocess_exec(command, *args, cwd=cwd, env=cli_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.communicate()
        raise
    try:
        envelope = json.loads(stdout.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError(f"Agent Mail 未返回有效结果（退出码 {process.returncode}），请检查授权") from None
    if process.returncode or envelope.get("ok") is False:
        error = (envelope.get("error") or {}).get("message") or "请检查发信授权或平台额度"
        raise ValueError(f"Agent Mail：{mask_text(str(error))[:400]}（退出码 {process.returncode}）")
    return envelope


async def profile() -> dict:
    result = await run_cli("+me")
    aliases = (result.get("data") or {}).get("aliases") or []
    primary = next((a for a in aliases if a.get("is_primary")), aliases[0] if aliases else {})
    return {"connected": bool(primary.get("email")), "sender": primary.get("email", ""),
            "aliases": [a.get("email") for a in aliases if a.get("email")]}


async def send(recipient: str, title: str, body: str) -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="email-", dir=settings.data_dir) as folder:
        Path(folder, "notice.txt").write_text(body, encoding="utf-8")
        result = await run_cli("message", "+send", "--to", recipient, "--subject", title,
                               "--body-file", "./notice.txt", "--body-format", "plain", "--confirmed", cwd=folder)
    if not (result.get("queued") is True or (result.get("data") or {}).get("queued") is True):
        raise ValueError("Agent Mail 未确认邮件进入发送队列，未计为发送成功")


async def _authorize() -> None:
    global _login_process
    try:
        command = executable()
        if not command:
            raise ValueError("未安装 Agent Mail 工具，请按操作文档安装后重试")
        _login_process = await asyncio.create_subprocess_exec(command, "auth", "login", env=cli_env(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

        async def consume():
            while line := await _login_process.stdout.readline():
                for url in re.findall(r"https://[^\s\x1b]+", line.decode("utf-8", errors="replace")):
                    parsed = urlparse(url)
                    if parsed.hostname == "agent.qq.com" and parsed.path.startswith("/page/oauth"):
                        _login.update(state="waiting", url=url)
            return await _login_process.wait()

        code = await asyncio.wait_for(consume(), 600)
        if code:
            raise ValueError(f"授权未完成（退出码 {code}），请重新点击连接；不会自动重试授权")
        _login.update(state="complete", url="")
    except Exception as exc:  # noqa: BLE001
        _login.update(state="error", url="", error=mask_text(str(exc))[:400])
    finally:
        if _login_process and _login_process.returncode is None:
            _login_process.kill()
            await _login_process.wait()
        _login_process = None


async def start_login() -> dict:
    global _login_task
    if not _login_task or _login_task.done():
        _login.update(state="starting", url="", error="")
        _login_task = asyncio.create_task(_authorize())
    return dict(_login)


def login_status() -> dict:
    return dict(_login)


async def stop_login() -> None:
    if _login_task and not _login_task.done():
        _login_task.cancel()
        try:
            await _login_task
        except asyncio.CancelledError:
            pass
