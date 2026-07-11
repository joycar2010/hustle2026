#!/bin/bash
# Tail logs from a specific shard
# Usage: ./logs-tail.sh [0|1|2] [lines]

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 [0|1|2] [lines=50]"
    echo "  0 = Machine A shard 0"
    echo "  1 = Machine B shard 1"
    echo "  2 = Machine C shard 2"
    exit 1
fi

SHARD_ID=$1
LINES=${2:-50}
KEY="~/.ssh/cex-trading-key2.pem"

case $SHARD_ID in
    0)
        MACHINE="ec2-user@57.183.43.62"
        NAME="Machine A"
        ;;
    1)
        MACHINE="ec2-user@54.65.42.207"
        NAME="Machine B"
        ;;
    2)
        MACHINE="ec2-user@57.181.130.126"
        NAME="Machine C"
        ;;
    *)
        echo "Invalid shard ID: $SHARD_ID"
        exit 1
        ;;
esac

echo "=== Logs from shard $SHARD_ID on $NAME (last $LINES lines) ==="
ssh -i $KEY $MACHINE "sudo journalctl -u cex-arb-engine@$SHARD_ID -n $LINES --no-pager"
