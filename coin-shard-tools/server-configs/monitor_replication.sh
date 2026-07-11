#!/bin/bash
# PostgreSQL 主从复制监控脚本（可配合 cron 定期运行）

PG_DSN='postgresql://postgres:***@127.0.0.1:5432/cex_trading'
ALERT_LAG_SECONDS=10
ALERT_FILE="/tmp/pg_replication_alert.flag"

# 检查复制连接数
REPLICA_COUNT=$(psql "$PG_DSN" -t -c "SELECT count(*) FROM pg_stat_replication;" 2>/dev/null | xargs)

if [ -z "$REPLICA_COUNT" ] || [ "$REPLICA_COUNT" -eq 0 ]; then
    echo "[ALERT] $(date): No replica connections found!" | tee -a /var/log/pg_replication_monitor.log
    touch "$ALERT_FILE"
    exit 1
fi

# 检查复制延迟
MAX_LAG_BYTES=$(psql "$PG_DSN" -t -c "
    SELECT COALESCE(MAX(pg_wal_lsn_diff(sent_lsn, replay_lsn)), 0)
    FROM pg_stat_replication;
" 2>/dev/null | xargs)

MAX_LAG_MB=$(echo "scale=2; $MAX_LAG_BYTES / 1024 / 1024" | bc)

# 检查时间延迟
REPLAY_LAG=$(psql "$PG_DSN" -t -c "
    SELECT COALESCE(EXTRACT(EPOCH FROM MAX(replay_lag)), 0)
    FROM pg_stat_replication;
" 2>/dev/null | xargs)

REPLAY_LAG_INT=${REPLAY_LAG%.*}

if [ "$REPLAY_LAG_INT" -gt $ALERT_LAG_SECONDS ]; then
    echo "[ALERT] $(date): Replication lag is ${REPLAY_LAG}s (threshold: ${ALERT_LAG_SECONDS}s), ${MAX_LAG_MB}MB behind" | tee -a /var/log/pg_replication_monitor.log
    touch "$ALERT_FILE"
    exit 1
fi

# 一切正常
if [ -f "$ALERT_FILE" ]; then
    echo "[RECOVERED] $(date): Replication healthy again - $REPLICA_COUNT replicas, lag: ${REPLAY_LAG}s" | tee -a /var/log/pg_replication_monitor.log
    rm -f "$ALERT_FILE"
fi

echo "[OK] $(date): $REPLICA_COUNT replicas connected, lag: ${REPLAY_LAG}s, ${MAX_LAG_MB}MB"
exit 0
