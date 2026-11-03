#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ ! -f .env ]]; then echo "缺少 .env；请先 cp .env.example .env 并配置强密码。" >&2; exit 1; fi
mkdir -p backups
# Credentials stay inside postgres; pg_dump stream is compressed before leaving its container.
docker compose exec -T postgres sh -ec 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists | gzip -c' > "backups/qbot-$(date +%Y%m%d-%H%M%S).sql.gz"
python3 -c 'from pathlib import Path; p=Path("backups"); fs=sorted(p.glob("qbot-*.sql.gz"),key=lambda f:f.stat().st_mtime,reverse=True); [f.unlink() for f in fs[14:]]'
printf '备份完成：%s\n' "$(ls -t backups/qbot-*.sql.gz | head -1)"
