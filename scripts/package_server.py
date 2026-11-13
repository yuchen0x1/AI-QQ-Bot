"""Package application sources for server upload; exclude local data and credentials."""

import argparse
from pathlib import Path
import subprocess
import zipfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".downloads/qbot-server.zip")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    allowed_dirs = {"backend", "frontend", "nginx", "docs", "scripts"}
    excluded_dirs = {".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "data", "backups"}
    root_files = {".env.example", ".dockerignore", "docker-compose.yml", "README.md", "DEPLOYMENT.md", "LICENSE", "backup.sh", "restore.sh"}
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root, check=True, capture_output=True)
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    written = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            relative = Path(name)
            source = root / relative
            if relative.parts[0] not in allowed_dirs and name not in root_files:
                continue
            if any(part in excluded_dirs for part in relative.parts) or source.is_symlink() or not source.is_file():
                continue
            resolved = source.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if resolved == output:
                continue
            if source.name.startswith(".env") and name != ".env.example":
                continue
            if source.suffix.lower() in {".log", ".db", ".sqlite3", ".pyc", ".zip", ".tsbuildinfo"}:
                continue
            archive.write(source, name)
            written += 1
    print(f"已生成 {output}（{written} 个文件），不含本地 .env、Token、数据库或依赖目录。")


if __name__ == "__main__":
    main()
