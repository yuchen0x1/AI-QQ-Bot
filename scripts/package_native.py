"""Create a server-ready update bundle with prebuilt UI and no live configuration."""

import argparse
import io
import json
from pathlib import Path
import tarfile

from prepare_release import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    prepare(root, args.tag)
    if not (root / "frontend/dist/index.html").is_file():
        parser.error("Build the frontend before creating the native update bundle")
    version = args.tag[1:]
    prefix = "qbot-ai-" + version
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sources = [
        "backend/app",
        "backend/migrations",
        "backend/plugins",
        "backend/requirements.txt",
        "backend/alembic.ini",
        "frontend/dist",
        "frontend/package.json",
    ]
    with tarfile.open(args.output, "w:gz") as archive:
        for source in sources:
            path = root / source
            files = sorted(path.rglob("*")) if path.is_dir() else [path]
            for file in files:
                if file.is_dir():
                    continue
                if file.is_symlink() or "__pycache__" in file.parts or file.suffix in {".pyc", ".db", ".log"}:
                    continue
                if file.name.startswith(".env") or not file.resolve().is_relative_to(root):
                    continue
                archive.add(file, arcname=prefix + "/" + file.relative_to(root).as_posix(), recursive=False)
        manifest = json.dumps(
            {"version": version, "format": "native-systemd-v1", "maintenance_protocol": 1, "python": "3.12"}
        ).encode()
        info = tarfile.TarInfo(prefix + "/qbot-update.json")
        info.size, info.mode = len(manifest), 0o644
        archive.addfile(info, io.BytesIO(manifest))
    print(f"Native update bundle ready: {args.output}")


if __name__ == "__main__":
    main()
