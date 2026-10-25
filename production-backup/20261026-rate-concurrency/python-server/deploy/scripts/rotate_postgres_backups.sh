#!/usr/bin/env bash
# Rotate compressed PostgreSQL backups and prune only expired operational logs.
# This script is intentionally fail-closed: it refuses to create a backup when
# the filesystem is too full and never deletes a backup until a newer backup
# has been completed successfully.
set -Eeuo pipefail

BACKUP_ROOT="${CEX_BACKUP_ROOT:-/home/ec2-user/coin-backups/postgres}"
MAX_BACKUPS="${CEX_BACKUP_MAX_COUNT:-7}"
MIN_FREE_PERCENT="${CEX_BACKUP_MIN_FREE_PERCENT:-15}"
MIN_FREE_MB="${CEX_BACKUP_MIN_FREE_MB:-4096}"
DB_HOST="${CEX_DB_HOST:-127.0.0.1}"
DB_PORT="${CEX_DB_PORT:-5432}"
DB_NAME="${CEX_DB_NAME:-cex_trading}"
DB_USER="${CEX_DB_USER:-postgres}"
DB_URL="${CEX_DATABASE_URL:-}"
LOCK_FILE="${CEX_BACKUP_LOCK:-/tmp/cex-postgres-backup.lock}"

mkdir -p "$BACKUP_ROOT" "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "backup already running" >&2; exit 0; }

free_mb() { df -Pm "$BACKUP_ROOT" | awk 'NR==2 {print $4}'; }
free_pct() { df -P "$BACKUP_ROOT" | awk 'NR==2 {gsub(/%/,"",$5); print 100-$5}'; }
require_space() {
  local pct mb
  pct="$(free_pct)"; mb="$(free_mb)"
  if (( pct < MIN_FREE_PERCENT || mb < MIN_FREE_MB )); then
    echo "refusing backup: ${pct}% / ${mb}MB free; minimum ${MIN_FREE_PERCENT}% / ${MIN_FREE_MB}MB" >&2
    exit 20
  fi
}

require_space
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
tmp="${BACKUP_ROOT}/.cex_trading-${stamp}.dump.tmp"
out="${BACKUP_ROOT}/cex_trading-${stamp}.dump"
trap 'rm -f -- "$tmp"' EXIT

# Custom format is compressed by pg_dump and supports selective restores. The
# stream is written atomically so interrupted dumps are never retained as valid.
if [[ -n "$DB_URL" ]]; then
  pg_dump "$DB_URL" --format=custom --compress=6 --no-owner --no-privileges >"$tmp"
else
  PGPASSWORD="${PGPASSWORD:?set PGPASSWORD or CEX_DATABASE_URL before running backup}" pg_dump \
    --format=custom --compress=6 --no-owner --no-privileges \
    --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="$DB_NAME" \
    >"$tmp"
fi
test -s "$tmp"
chmod 600 "$tmp"
mv -f -- "$tmp" "$out"
trap - EXIT

# Prune by count only after a successful new dump. Keep the newest
# MAX_BACKUPS. The count cap is
# the final guard against an unbounded directory; the newest files are kept.
mapfile -t backups < <(find "$BACKUP_ROOT" -maxdepth 1 -type f -name 'cex_trading-*.dump' -printf '%T@ %p\n' | sort -nr | awk '{sub(/^[^ ]+ /, ""); print}')
if (( ${#backups[@]} > MAX_BACKUPS )); then
  for old in "${backups[@]:$MAX_BACKUPS}"; do rm -f -- "$old"; done
fi

# Remove only old high-volume operational logs. User, rule, position and
# accounting tables are deliberately excluded. VACUUM (not VACUUM FULL) is
# used because it does not require a second copy of a large table.
if [[ -n "$DB_URL" ]]; then
  psql "$DB_URL" --set=ON_ERROR_STOP=1 --quiet <<'SQL'
DELETE FROM trade_logs WHERE created_at < now() - interval '90 days';
DELETE FROM audit_logs WHERE created_at < now() - interval '90 days';
DELETE FROM proxy_health_logs WHERE checked_at < now() - interval '30 days';
VACUUM (ANALYZE) trade_logs;
VACUUM (ANALYZE) audit_logs;
VACUUM (ANALYZE) proxy_health_logs;
SQL
else
  PGPASSWORD="${PGPASSWORD:?set PGPASSWORD or CEX_DATABASE_URL before running backup}" psql \
    --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="$DB_NAME" \
    --set=ON_ERROR_STOP=1 --quiet <<'SQL'
DELETE FROM trade_logs WHERE created_at < now() - interval '90 days';
DELETE FROM audit_logs WHERE created_at < now() - interval '90 days';
DELETE FROM proxy_health_logs WHERE checked_at < now() - interval '30 days';
VACUUM (ANALYZE) trade_logs;
VACUUM (ANALYZE) audit_logs;
VACUUM (ANALYZE) proxy_health_logs;
SQL
fi

echo "backup complete: ${out} ($(du -h "$out" | awk '{print $1}')); free=$(free_pct)%/$(free_mb)MB"


