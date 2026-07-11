#!/bin/bash
# PostgreSQL 从库提升为主库工具（手动故障切换）

set -e

echo '========================================='
echo '⚠️  PostgreSQL FAILOVER - Promote Replica to Primary'
echo '========================================='
echo
echo 'This will promote this replica (10.0.1.103) to PRIMARY.'
echo 'Make sure the old primary (10.0.1.18) is stopped first!'
echo
read -p 'Type YES to continue: ' confirm

if [ "$confirm" != "YES" ]; then
    echo 'Aborted.'
    exit 1
fi

echo
echo '--- Step 1: Check current status ---'
RECOVERY_STATUS=$(sudo -u postgres psql -t -c 'SELECT pg_is_in_recovery();' | xargs)

if [ "$RECOVERY_STATUS" = "f" ]; then
    echo '❌ ERROR: This server is already in PRIMARY mode!'
    exit 1
fi

echo '✓ Current mode: REPLICA'

echo
echo '--- Step 2: Promote replica to primary ---'
sudo -u postgres pg_ctl promote -D /var/lib/pgsql/data

echo
echo 'Waiting 5 seconds for promotion to complete...'
sleep 5

echo
echo '--- Step 3: Verify promotion ---'
NEW_STATUS=$(sudo -u postgres psql -t -c 'SELECT pg_is_in_recovery();' | xargs)

if [ "$NEW_STATUS" = "f" ]; then
    echo '✅ SUCCESS: Server is now PRIMARY (read-write)'
else
    echo '❌ ERROR: Promotion failed, still in recovery mode'
    exit 1
fi

echo
echo '--- Step 4: Check write capability ---'
sudo -u postgres psql -d cex_trading -c "
    CREATE TABLE IF NOT EXISTS _failover_test (promoted_at timestamptz);
    INSERT INTO _failover_test VALUES (now());
    SELECT * FROM _failover_test ORDER BY promoted_at DESC LIMIT 1;
    DROP TABLE _failover_test;
" && echo '✓ Write test passed'

echo
echo '========================================='
echo '✅ FAILOVER COMPLETE'
echo '========================================='
echo
echo 'Next steps:'
echo '1. Update all application connection strings to: 10.0.1.103:5432'
echo '2. Restart application services'
echo '3. Monitor new primary with: ~/tools/check_replication.sh'
echo
