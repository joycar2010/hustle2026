#!/bin/bash
# Coin Engine Shard Health Check Tool
# 检查三台机器上的 shard 状态

set -e

KEY="~/.ssh/cex-trading-key2.pem"
MACHINE_A="ec2-user@57.183.43.62"
MACHINE_B="ec2-user@54.65.42.207"
MACHINE_C="ec2-user@57.181.130.126"

echo "=================================="
echo "Coin Engine Shard Health Check"
echo "$(date)"
echo "=================================="
echo

# Function to check shard status
check_shard() {
    local machine=$1
    local name=$2
    local shard_id=$3
    
    echo "[$name] Shard $shard_id:"
    ssh -i $KEY $machine "
        status=\$(sudo systemctl is-active cex-arb-engine@$shard_id 2>/dev/null || echo 'inactive')
        pid=\$(ps aux | grep '[p]ython3 -m engine --shard-id=$shard_id' | awk '{print \$2}')
        if [ -n \"\$pid\" ]; then
            mem=\$(ps -p \$pid -o rss= | awk '{printf \"%.1fM\", \$1/1024}')
            cpu=\$(ps -p \$pid -o %cpu= | awk '{print \$1\"%\"}')
            echo \"  Status: \$status\"
            echo \"  PID: \$pid\"
            echo \"  Memory: \$mem\"
            echo \"  CPU: \$cpu\"
        else
            echo \"  Status: \$status (no process found)\"
        fi
    " 2>/dev/null || echo "  ERROR: Cannot connect to $name"
    echo
}

# Check all shards
check_shard "$MACHINE_A" "Machine A (10.0.1.18)" "0"
check_shard "$MACHINE_B" "Machine B (10.0.1.103)" "1"
check_shard "$MACHINE_C" "Machine C (10.0.1.12)" "2"

# Check database heartbeats
echo "[Database] Worker Heartbeats:"
ssh -i $KEY $MACHINE_A "
    PGPASSWORD="${CEX_PG_PASSWORD:?set CEX_PG_PASSWORD env var}" psql -h 127.0.0.1 -U postgres -d cex_trading -t -c \"
        SELECT 
            scope,
            status,
            ROUND(EXTRACT(EPOCH FROM (NOW() - last_heartbeat))::numeric, 1) as age_sec
        FROM engine_state 
        WHERE scope LIKE 'sub:%' OR scope LIKE 'shard:%'
        ORDER BY scope;
    \"
" 2>/dev/null | grep -v '^$' || echo "  ERROR: Cannot query database"

echo
echo "Health check complete."
