#!/bin/bash
# Monitor load distribution across all 3 machines

KEY="~/.ssh/cex-trading-key2.pem"

echo "=================================="
echo "Coin Engine Load Monitor"
echo "$(date)"
echo "=================================="
echo

monitor_machine() {
    local machine=$1
    local name=$2
    
    echo "[$name]"
    ssh -i $KEY $machine "
        load=\$(uptime | awk -F'load average:' '{print \$2}')
        cpu=\$(top -bn1 | grep 'Cpu(s)' | awk '{printf \"us=%.1f%% sy=%.1f%%\", \$2, \$4}')
        mem=\$(free -h | grep Mem | awk '{printf \"used=%s total=%s\", \$3, \$2}')
        echo \"  Load avg:\$load\"
        echo \"  CPU: \$cpu\"
        echo \"  Memory: \$mem\"
    " 2>/dev/null || echo "  ERROR: Cannot connect"
    echo
}

monitor_machine "ec2-user@57.183.43.62" "Machine A (10.0.1.18, 2 cores, shard 0)"
monitor_machine "ec2-user@54.65.42.207" "Machine B (10.0.1.103, 4 cores, shard 1)"
monitor_machine "ec2-user@57.181.130.126" "Machine C (10.0.1.12, 2 cores, shard 2)"

echo "Monitor complete."
