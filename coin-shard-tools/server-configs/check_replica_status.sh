#!/bin/bash
# PostgreSQL 从库状态检查工具

echo '========================================='
echo 'PostgreSQL Replica Status Check'
echo 'Replica Server: 10.0.1.103'
echo 'Time: '$(date)
echo '========================================='
echo

echo '--- Replica Mode ---'
sudo -u postgres psql -c "
  SELECT 
    pg_is_in_recovery() AS is_replica,
    CASE 
      WHEN pg_is_in_recovery() THEN 'Replica (Read-Only)'
      ELSE 'Primary (Read-Write) ⚠️'
    END AS mode;
" 2>/dev/null || echo 'ERROR: Cannot connect to database'

echo
echo '--- Replication Lag ---'
sudo -u postgres psql -c "
  SELECT 
    now() - pg_last_xact_replay_timestamp() AS replication_lag,
    pg_last_xact_replay_timestamp() AS last_replay_time,
    CASE 
      WHEN now() - pg_last_xact_replay_timestamp() < interval '5 seconds' THEN '✓ Healthy'
      WHEN now() - pg_last_xact_replay_timestamp() < interval '30 seconds' THEN '⚠️ Warning'
      ELSE '❌ Critical'
    END AS status;
" 2>/dev/null

echo
echo '--- WAL Receiver Status ---'
sudo -u postgres psql -c "
  SELECT 
    status,
    sender_host,
    sender_port,
    slot_name,
    conninfo
  FROM pg_stat_wal_receiver;
" 2>/dev/null

echo
echo '--- WAL Replay Status ---'
sudo -u postgres psql -c "
  SELECT 
    pg_last_wal_receive_lsn() AS received_lsn,
    pg_last_wal_replay_lsn() AS replayed_lsn,
    pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()) / 1024 AS replay_pending_kb;
" 2>/dev/null

echo
echo '--- PostgreSQL Service Status ---'
systemctl is-active postgresql && echo '✓ Service: active' || echo '❌ Service: inactive'
systemctl is-enabled postgresql && echo '✓ Enabled on boot' || echo '⚠️ Not enabled on boot'

echo '========================================='
