"""Executed as the isolated build user, with no application credentials."""

from pathlib import Path
import os
import subprocess
import sys

folder = Path(sys.argv[1]).resolve()
python = Path(sys.argv[2]).resolve()
environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(folder), "PIP_NO_CACHE_DIR": "1"}
subprocess.run([str(python), "-m", "venv", str(folder / ".venv")], check=True, env=environment, timeout=60)
subprocess.run(
    [
        str(folder / ".venv/bin/python"),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--only-binary=:all:",
        "-r",
        str(folder / "backend/requirements.txt"),
    ],
    check=True,
    cwd=folder,
    env=environment,
    timeout=540,
)
os.chmod(folder, 0o755)
