# Coin Engine Shard Management Tools

运维工具集用于管理跨三台机器部署的 coin 引擎 shard。

## 机器拓扑

```
Machine A (57.183.43.62, 10.0.1.18) - 2 cores
├─ Shard 0
├─ PostgreSQL (10.0.1.18:5432)
└─ systemctl: cex-arb-engine@0

Machine B (54.65.42.207, 10.0.1.103) - 4 cores
├─ Shard 1
└─ systemctl: cex-arb-engine@1

Machine C (57.181.130.126, 10.0.1.12) - 2 cores
├─ Shard 2
└─ systemctl: cex-arb-engine@2

Shared Resources:
├─ PostgreSQL: 10.0.1.18:5432
└─ Redis: 10.0.1.95:6379
```

## 工具列表

### 1. health-check.sh
检查所有 shard 的健康状态（进程、内存、CPU、心跳）

```bash
./health-check.sh
```

输出示例：
```
[Machine A (10.0.1.18)] Shard 0:
  Status: active
  PID: 4021545
  Memory: 156.2M
  CPU: 15.3%

[Database] Worker Heartbeats:
 shard:0 | RUNNING |  2.1
 sub:9   | RUNNING |  3.5
 sub:10  | RUNNING |  3.7
```

### 2. restart-shard.sh
重启指定的 shard

```bash
./restart-shard.sh [0|1|2]
```

示例：
```bash
./restart-shard.sh 1   # 重启 Machine B 上的 shard 1
```

### 3. load-monitor.sh
监控三台机器的负载分布

```bash
./load-monitor.sh
```

输出示例：
```
[Machine A (10.0.1.18, 2 cores, shard 0)]
  Load avg: 1.15, 1.58, 2.19
  CPU: us=62.9% sy=11.4%
  Memory: used=2.1G total=3.7G
```

### 4. logs-tail.sh
查看指定 shard 的日志

```bash
./logs-tail.sh [0|1|2] [lines]
```

示例：
```bash
./logs-tail.sh 1 100   # 查看 shard 1 最近 100 行日志
./logs-tail.sh 2       # 查看 shard 2 最近 50 行日志（默认）
```

## 常见运维场景

### 场景 1: 日常健康检查
```bash
./health-check.sh
```

### 场景 2: 某个 shard 出现问题需要重启
```bash
# 先查看日志
./logs-tail.sh 1 200

# 重启 shard
./restart-shard.sh 1

# 验证恢复
./health-check.sh
```

### 场景 3: 监控负载分布
```bash
# 循环监控（每 30 秒一次）
watch -n 30 ./load-monitor.sh
```

### 场景 4: 查找错误
```bash
# 查看所有 shard 的最近错误
for i in 0 1 2; do
    echo "=== Shard $i errors ==="
    ./logs-tail.sh $i 200 | grep -i error
done
```

## 手动操作命令

如果需要直接 SSH 操作：

```bash
# Machine A
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.183.43.62
sudo systemctl status cex-arb-engine@0
sudo journalctl -u cex-arb-engine@0 -f

# Machine B
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@54.65.42.207
sudo systemctl status cex-arb-engine@1
sudo journalctl -u cex-arb-engine@1 -f

# Machine C
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.181.130.126
sudo systemctl status cex-arb-engine@2
sudo journalctl -u cex-arb-engine@2 -f
```

## 数据库查询

```bash
# 在 Machine A 上查询 engine_state
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.183.43.62
PGPASSWORD='***' psql -h 127.0.0.1 -U postgres -d cex_trading

# 查看所有 shard 和 worker 状态
SELECT scope, status, 
       EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) as age_sec,
       pid
FROM engine_state 
WHERE scope LIKE 'shard:%' OR scope LIKE 'sub:%'
ORDER BY scope;
```

## 紧急回滚

如果跨机部署出现问题，回滚到单机部署：

```bash
# 停止 Machine B 和 C 上的 shard
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@54.65.42.207 "sudo systemctl stop cex-arb-engine@1"
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.181.130.126 "sudo systemctl stop cex-arb-engine@2"

# 在 Machine A 上重启所有 shard
ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@57.183.43.62 "
  sudo systemctl enable cex-arb-engine@1
  sudo systemctl enable cex-arb-engine@2
  sudo systemctl start cex-arb-engine@1
  sudo systemctl start cex-arb-engine@2
"

# 验证
./health-check.sh
```

## 已知问题

1. **Stale PIDs in engine_state**
   - `shard:1` 和 `shard:2` 的 PID 字段显示旧值
   - Worker 级别心跳（`sub:9`, `sub:10`）正常更新
   - 影响：低（系统正常运行）

2. **Binance API -2015 错误**
   - 新机器 IP 可能需要在 Binance 白名单
   - Machine B: 54.65.42.207
   - Machine C: 57.181.130.126

3. **目录路径不一致**
   - Machine A: ~/hustlecoin-cex/python-business
   - Machine B/C: ~/hustlecoin-cex/hustlecoin-cex/python-business

## 联系与支持

部署日期：2026-07-11
部署版本：coin branch, commit c86a8916
