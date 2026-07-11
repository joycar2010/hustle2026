#!/bin/bash
# PostgreSQL 主从复制健康检查工具

PG_DSN='postgresql://postgres:***@127.0.0.1:5432/cex_trading'

echo '========================================='
echo 'PostgreSQL Replication Health Check'
echo 'Primary Server: 10.0.1.18'
echo 'Time: '$(date)
echo '========================================='
echo

echo '--- Replication Connections ---'
psql "$PG_DSN" -c "
  SELECT 
    client_addr AS replica_ip,
    state,
    sync_state,
    pg_wal_lsn_diff(sent_lsn, replay_lsn) / 1024 / 1024 AS replay_lag_mb,
    write_lag,
    flush_lag,
    replay_lag,
    now() - backend_start AS uptime
  FROM pg_stat_replication;
" 2>/dev/null || echo 'ERROR: Cannot connect to primary database'

echo
echo '--- WAL Status ---'
psql "$PG_DSN" -c "
  SELECT 
    pg_current_wal_lsn() AS current_wal_lsn,
    pg_walfile_name(pg_current_wal_lsn()) AS current_wal_file;
" 2>/dev/null

echo
echo '--- Database Size ---'
psql "$PG_DSN" -c "
  SELECT pg_size_pretty(pg_database_size('cex_trading')) AS database_size;
" 2>/dev/null

echo
echo '--- Active Connections ---'
psql "$PG_DSN" -c "
  SELECT count(*) AS total_connections,
         count(*) FILTER (WHERE state = 'active') AS active_queries
  FROM pg_stat_activity
  WHERE datname = 'cex_trading';
" 2>/dev/null

echo '========================================='
