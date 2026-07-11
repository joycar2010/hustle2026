# Coin Engine Shard - Quick Reference Card

## Machine Topology
```
Machine A (57.183.43.62) → Shard 0 + PostgreSQL
Machine B (54.65.42.207) → Shard 1
Machine C (57.181.130.126) → Shard 2
```

## Quick Commands

### Health Check (most common)
```bash
~/coin-shard-tools/health-check.sh
```

### Restart a Shard
```bash
~/coin-shard-tools/restart-shard.sh [0|1|2]
```

### Check Load Distribution
```bash
~/coin-shard-tools/load-monitor.sh
```

### View Logs
```bash
~/coin-shard-tools/logs-tail.sh [0|1|2] [lines]
```

## Direct SSH Access

### Machine A (Shard 0)
```bash
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.183.43.62
sudo systemctl status cex-arb-engine@0
sudo journalctl -u cex-arb-engine@0 -f
```

### Machine B (Shard 1)
```bash
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@54.65.42.207
sudo systemctl status cex-arb-engine@1
sudo journalctl -u cex-arb-engine@1 -f
```

### Machine C (Shard 2)
```bash
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.181.130.126
sudo systemctl status cex-arb-engine@2
sudo journalctl -u cex-arb-engine@2 -f
```

## Database Queries

### Check Heartbeats
```bash
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.183.43.62
PGPASSWORD='***' psql -h 127.0.0.1 -U postgres -d cex_trading -c "
  SELECT scope, status, 
         EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) as age_sec
  FROM engine_state 
  WHERE scope LIKE 'sub:%' OR scope LIKE 'shard:%'
  ORDER BY scope;"
```

## Emergency Procedures

### Restart All Shards
```bash
for i in 0 1 2; do ~/coin-shard-tools/restart-shard.sh $i; done
```

### Rollback to Single Machine
```bash
# Stop B & C
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@54.65.42.207 "sudo systemctl stop cex-arb-engine@1"
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.181.130.126 "sudo systemctl stop cex-arb-engine@2"

# Restart 1 & 2 on Machine A
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.183.43.62 "
  sudo systemctl enable cex-arb-engine@{1,2}
  sudo systemctl start cex-arb-engine@{1,2}"
```

## What to Monitor

### Healthy System Signs
- All 3 shards show "Status: active"
- Worker heartbeats (sub:9, sub:10) < 10 seconds
- Machine A load < 2.0
- No Binance API errors (after IP whitelisting)

### Warning Signs
- Any shard status != active
- Worker heartbeat age > 30 seconds
- Machine A load > 3.0
- Repeated API -2015 errors

## Known Issues

1. **Stale PIDs in engine_state** - Ignore, check worker heartbeats instead
2. **Binance API -2015** - Whitelist IPs 54.65.42.207 and 57.181.130.126
3. **Different directory paths** - Normal, systemd configured correctly

## Contact

Deployment: 2026-07-11  
Tools: ~/coin-shard-tools/  
Docs: ~/coin-shard-tools/README.md
