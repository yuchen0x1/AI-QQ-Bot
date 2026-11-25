#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
verify_only=false
if [[ "${1:-}" == '--verify-only' ]]; then verify_only=true; shift; fi
if [[ $# -ne 1 || ! -f "$1" ]]; then echo "用法：$0 [--verify-only] backups/qbot-....sql.gz" >&2; exit 2; fi
ENV_FILE="${QBOT_ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || { echo '缺少环境配置。' >&2; exit 1; }
export QBOT_ENV_FILE="$ENV_FILE"
archive="$1"
python3 scripts/backup_storage.py verify "$archive"
compose=(docker compose --env-file "$ENV_FILE")
rehearsal="qbot_restore_$(date +%s)_$$_$RANDOM"
maintenance=false
cleanup() {
  result=$?
  "${compose[@]}" exec -T postgres sh -ec 'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$rehearsal" || true
  if [[ "$result" != 0 && "$maintenance" == true ]]; then
    echo '恢复失败：backend/worker 保持停止。请检查恢复前快照和日志，再手动启动服务。' >&2
  fi
  exit "$result"
}
trap cleanup EXIT
"${compose[@]}" exec -T postgres sh -ec 'createdb -U "$POSTGRES_USER" "$1"' sh "$rehearsal"
gzip -dc -- "$archive" | "${compose[@]}" exec -T postgres sh -ec \
  'exec psql --single-transaction -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"' sh "$rehearsal"
schema_ok="$("${compose[@]}" exec -T postgres sh -ec \
  'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -At -c "SELECT CASE WHEN to_regclass('\''public.accounts'\'') IS NOT NULL AND to_regclass('\''public.users'\'') IS NOT NULL AND to_regclass('\''public.system_settings'\'') IS NOT NULL AND to_regclass('\''public.alembic_version'\'') IS NOT NULL THEN 1 ELSE 0 END"' sh "$rehearsal")"
[[ "$schema_ok" == '1' ]] || { echo '隔离恢复缺少必要业务表，拒绝覆盖运行数据库。' >&2; exit 1; }
revision="$("${compose[@]}" exec -T postgres sh -ec \
  'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -At -c "SELECT version_num FROM public.alembic_version"' sh "$rehearsal")"
python3 scripts/backup_storage.py revision "$revision"
if [[ "$verify_only" == true ]]; then echo '隔离数据库恢复演练通过；未修改运行数据库。'; exit 0; fi
printf '隔离演练通过。恢复将覆盖当前数据库；请同时停止所有外部写入实例。\n备份文件：%s\n' "$archive" >&2
read -r -p '输入 RESTORE 确认进入维护模式并继续：' confirmation
[[ "$confirmation" == 'RESTORE' ]] || { echo '已取消。'; exit 1; }
running="$("${compose[@]}" ps --services --status running)"
maintenance=true
"${compose[@]}" stop backend worker
bash ./backup.sh
gzip -dc -- "$archive" | "${compose[@]}" exec -T postgres sh -ec \
  'exec psql --single-transaction -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
for service in backend worker; do
  if printf '%s\n' "$running" | grep -qx "$service"; then "${compose[@]}" start "$service"; fi
done
maintenance=false
echo '恢复完成；恢复前快照保存在 backups/，请核对就绪探针与业务数据。'
