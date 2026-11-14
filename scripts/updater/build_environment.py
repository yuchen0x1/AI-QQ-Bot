"""Executed as the isolated build user, with no application credentials."""

from pathlib import Path
import os
import subprocess
import sys
from urllib.parse import urlparse

folder = Path(sys.argv[1]).resolve()
python = Path(sys.argv[2]).resolve()
index = sys.argv[3] if len(sys.argv) > 3 else ""
parsed = urlparse(index)
if index and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
    raise ValueError("pip 镜像源配置无效，需要不带凭据的 HTTPS 地址")
environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(folder), "PIP_NO_CACHE_DIR": "1"}
subprocess.run([str(python), "-m", "venv", str(folder / ".venv")], check=True, env=environment, timeout=60)
install_argv = [
    str(folder / ".venv/bin/python"),
    "-m",
    "pip",
    "install",
    "--disable-pip-version-check",
    "--no-input",
    "--only-binary=:all:",
]
if index:
    install_argv += ["-i", index]
install_argv += ["-r", str(folder / "backend/requirements.txt")]
subprocess.run(install_argv, check=True, cwd=folder, env=environment, timeout=540)
os.chmod(folder, 0o755)
