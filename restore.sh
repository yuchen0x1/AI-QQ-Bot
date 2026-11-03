#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ $# -ne 1 || ! -f "$1" ]]; then echo "用法：$0 backups/qbot-YYYYMMDD-HHMMSS.sql.gz" >&2; exit 2; fi
printf '警告：恢复将使用备份覆盖当前数据库中的对象。\n备份文件：%s\n' "$1" >&2
read -r -p '输入 RESTORE 确认继续：' confirmation
[[ "$confirmation" == "RESTORE" ]] || { echo '已取消。'; exit 1; }
gzip -dc -- "$1" | docker compose exec -T postgres sh -ec 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
echo '恢复完成。'
