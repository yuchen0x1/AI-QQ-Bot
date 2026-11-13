"""Generate a fresh server .env without printing secrets or overwriting existing config."""

import argparse
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    url = args.public_url.rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        parser.error("public-url 必须是完整站点地址，例如 https://qbot.example.com")
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if target.exists():
        parser.error(".env 已存在，为保护原有密钥与数据不会覆盖；请手动修改现有配置")
    content = (root / ".env.example").read_text(encoding="utf-8")
    replacements = {"PUBLIC_BASE_URL": url, "CORS_ORIGINS": url, "SCHEDULER_ENABLED": "true", "DEBUG": "false",
                    "SECRET_KEY": secrets.token_urlsafe(48), "ADMIN_PASSWORD": secrets.token_urlsafe(24),
                    "POSTGRES_PASSWORD": secrets.token_urlsafe(32), "REDIS_PASSWORD": secrets.token_urlsafe(32)}
    lines = [f"{key}={replacements[key]}" if "=" in line and (key := line.split("=", 1)[0]) in replacements else line for line in content.splitlines()]
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    print("已生成服务器 .env；随机管理员密码保存在 ADMIN_PASSWORD 中。")
    print("请妥善保管 .env。已有数据库迁移必须保留原 SECRET_KEY，不能用新密钥替换。")


if __name__ == "__main__":
    main()
