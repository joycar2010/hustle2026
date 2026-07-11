#!/bin/bash
# Restart a specific shard
# Usage: ./restart-shard.sh [0|1|2]

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 [0|1|2]"
    echo "  0 = Machine A (57.183.43.62)"
    echo "  1 = Machine B (54.65.42.207)"
    echo "  2 = Machine C (57.181.130.126)"
    exit 1
fi

SHARD_ID=$1
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

echo "Restarting shard $SHARD_ID on $NAME..."
ssh -i $KEY $MACHINE "sudo systemctl restart cex-arb-engine@$SHARD_ID"
echo "Waiting 5 seconds..."
sleep 5

echo "Checking status..."
ssh -i $KEY $MACHINE "sudo systemctl status cex-arb-engine@$SHARD_ID --no-pager | head -15"

echo
echo "Restart complete."
