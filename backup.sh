#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
ENV_FILE="${QBOT_ENV_FILE:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then echo "缺少环境配置；请先配置 .env 或 QBOT_ENV_FILE。" >&2; exit 1; fi
export QBOT_ENV_FILE="$ENV_FILE"
umask 077
mkdir -p backups
temporary="$(mktemp backups/.qbot-backup-XXXXXXXX.sql.gz)"
trap 'rm -f -- "$temporary"' EXIT
target="backups/qbot-$(date +%Y%m%d-%H%M%S)-${temporary##*.qbot-backup-}"
# Keep both processes in this pipefail shell; POSIX sh in postgres does not have pipefail.
docker compose --env-file "$ENV_FILE" exec -T postgres sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' \
  | gzip -c > "$temporary"
python3 scripts/backup_storage.py finalize "$temporary" "$target" --keep 14
printf '备份完成：%s\n' "$target"
