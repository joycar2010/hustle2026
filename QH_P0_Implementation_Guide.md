# QH系统P0阶段实施完整方案
# 全链路追踪与对账机制部署指南

## 一、已完成的准备工作

### 1.1 核心模块已上传至服务器
```
/opt/quanthedge/qh_command_tracer.py       (8.7KB) - 追踪器核心模块
/opt/quanthedge/qh_reconciliation_worker.py (13KB)  - 对账Worker
/opt/quanthedge/qh_p0_integration_patch.py  (9.6KB) - 集成指南
```

### 1.2 备份已创建
```
/opt/quanthedge/app.py.bak_p0_20260723_173447 (509KB) - 原始app.py备份
```

### 1.3 Python语法验证通过
```
✓ qh_command_tracer.py
✓ qh_reconciliation_worker.py
```

---

## 二、手动集成步骤 (预计2-3小时)

### 步骤1: 修改app.py添加import (5分钟)

**位置**: app.py 第9行后

**添加内容**:
```python
# P0.1: 全链路追踪模块
from qh_command_tracer import (
    init_tracer,
    get_tracer,
    CommandType,
    CommandStatus,
    TraceTimestamp
)
```

**位置**: app.py 第13行后 (R = redis.Redis(...) 之后)

**添加内容**:
```python
# P0.1: 初始化全链路追踪器
init_tracer(R)
```

---

### 步骤2: 修改cmd_open_pair添加追踪入口 (30分钟)

**位置**: app.py 约6415行, `async def cmd_open_pair(r:OpenPairReq):` 开始

**原代码**:
```python
async def cmd_open_pair(r:OpenPairReq):
    actor=_actor(r.license_key)
    if r.direction not in ("reverse","forward"):
        raise HTTPException(400,"direction 必须为 reverse 或 forward")
```

**修改为**:
```python
async def cmd_open_pair(r:OpenPairReq):
    # === P0.1: 创建command追踪 ===
    tracer = get_tracer()
    command_id = tracer.create_command(
        cmd_type=CommandType.OPEN_PAIR,
        username=r.username,
        symbol=r.symbol,
        direction=r.direction,
        metadata={
            "slots": r.slots,
            "slot": r.slot,
        }
    )
    
    try:
        actor=_actor(r.license_key)
        if r.direction not in ("reverse","forward"):
            raise HTTPException(400,"direction 必须为 reverse 或 forward")
        if not r.confirm:
            raise HTTPException(400,"二次确认未通过(confirm=true)")
        
        # === P0.1: 记录前置检查开始 ===
        tracer.record_timestamp(command_id, TraceTimestamp.PREFLIGHT_START)
        
        _maint_block_trading()
        await _conn_gate_exec()
        await _exec_owner_gate(r.username)
        
        # ... 继续原有代码 ...
```

**在前置检查完成后添加** (约在6450行,加载完模板t后):
```python
        # === P0.1: 前置检查完成 ===
        tracer.record_timestamp(command_id, TraceTimestamp.PREFLIGHT_DONE)
        tracer.update_status(command_id, CommandStatus.SUBMITTED)
```

**在函数末尾返回前修改** (约在6690行):
```python
    except HTTPException as he:
        # === P0.1: 记录失败 ===
        tracer.update_status(command_id, CommandStatus.FAILED)
        tracer.update_field(command_id, "failure_reason", str(he.detail))
        raise
    except Exception as e:
        # === P0.1: 记录异常 ===
        tracer.update_status(command_id, CommandStatus.FAILED)
        tracer.update_field(command_id, "failure_reason", str(e))
        raise
    finally:
        # === P0.1: 记录HTTP响应时间 ===
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
```

**修改最终返回** (约在6680行):
```python
    # 原返回逻辑
    # return {"ok":True, "demo":False, ...}
    
    # 修改为包含command_id
    result = {
        "ok": True,
        "command_id": command_id,  # 新增
        "demo": False,
        "direction": r.direction,
        "mode": mode,
        "opened": opened_count,
        ...
    }
    
    # 记录最终状态
    if opened_count > 0:
        tracer.update_status(command_id, CommandStatus.COMPLETED)
    
    return result
```

---

### 步骤3: 修改cmd_close_pair添加追踪 (30分钟)

**位置**: app.py 约6705行

**类似cmd_open_pair的修改,添加**:
1. 入口创建command_id
2. 前置检查时间戳
3. 异常捕获
4. 返回中包含command_id

---

### 步骤4: 添加查询命令状态端点 (10分钟)

**位置**: app.py 末尾,在最后一个路由后添加

**添加内容**:
```python
@app.get("/api/command/{command_id}")
async def get_command_status(command_id: str):
    """查询订单命令状态和追踪信息"""
    tracer = get_tracer()
    cmd = tracer.get_command(command_id)
    
    if not cmd:
        raise HTTPException(404, "命令不存在")
    
    # 计算各阶段延迟
    latencies = tracer.calculate_latencies(command_id)
    
    return {
        "command_id": command_id,
        "type": cmd.get("type"),
        "status": cmd.get("status"),
        "username": cmd.get("username"),
        "symbol": cmd.get("symbol"),
        "direction": cmd.get("direction"),
        "main_ticket": cmd.get("main_ticket"),
        "hedge_ticket": cmd.get("hedge_ticket"),
        "created_at": cmd.get(TraceTimestamp.API_RECEIVED),
        "latencies": latencies,
        "failure_reason": cmd.get("failure_reason"),
        "exposure_reason": cmd.get("exposure_reason"),
        "reconcile_result": cmd.get("reconcile_result"),
    }

@app.get("/api/commands/unknown")
async def list_unknown_commands():
    """列出所有UNKNOWN状态的命令"""
    tracer = get_tracer()
    unknown_cmds = tracer.list_unknown_commands(limit=50)
    
    return {
        "count": len(unknown_cmds),
        "commands": [tracer.get_command(cmd_id) for cmd_id in unknown_cmds]
    }
```

---

### 步骤5: 启动对账Worker (20分钟)

**方案A: 独立进程启动** (推荐)

创建独立启动脚本:

```bash
# /opt/quanthedge/start_reconciliation_worker.py
import asyncio
import os
import redis
import logging
from qh_reconciliation_worker import ReconciliationWorker
from qh_command_tracer import init_tracer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

async def main():
    # 初始化Redis
    redis_client = redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=3,
        decode_responses=True
    )
    
    # 初始化tracer
    init_tracer(redis_client)
    
    # 创建Worker
    worker = ReconciliationWorker(
        redis_client=redis_client,
        db_session=None,  # 暂时不需要DB
        bridge_main_url=os.environ.get("QH_BRIDGE_URL", "http://172.31.5.62:8041"),
        bridge_hedge_url=os.environ.get("QH_HEDGE_URL", "http://172.31.5.62:8042"),
        bridge_api_key=os.environ.get("QH_BRIDGE_KEY", "7af2221c27241dd524273d2752772aa43e6b18c0187dffbf")
    )
    
    # 启动
    await worker.start()

if __name__ == "__main__":
    asyncio.run(main())
```

**启动命令**:
```bash
cd /opt/quanthedge
export QH_BRIDGE_URL="http://172.31.5.62:8041"
export QH_HEDGE_URL="http://172.31.5.62:8042"
export QH_BRIDGE_KEY="7af2221c27241dd524273d2752772aa43e6b18c0187dffbf"

nohup /opt/quanthedge/venv/bin/python start_reconciliation_worker.py > /tmp/reconciliation_worker.log 2>&1 &

# 记录PID
echo $! > /tmp/reconciliation_worker.pid
```

**方案B: 集成到app.py** (备选)

在app.py中添加startup事件:
```python
from qh_reconciliation_worker import ReconciliationWorker

reconciliation_worker = None

@app.on_event("startup")
async def startup_event():
    global reconciliation_worker
    
    reconciliation_worker = ReconciliationWorker(
        redis_client=R,
        db_session=None,
        bridge_main_url=os.environ.get("QH_BRIDGE_URL"),
        bridge_hedge_url=os.environ.get("QH_HEDGE_URL"),
        bridge_api_key=os.environ.get("QH_BRIDGE_KEY")
    )
    
    asyncio.create_task(reconciliation_worker.start())
    print("ReconciliationWorker started")

@app.on_event("shutdown")
async def shutdown_event():
    global reconciliation_worker
    if reconciliation_worker:
        await reconciliation_worker.stop()
```

---

### 步骤6: 语法检查和测试 (20分钟)

```bash
cd /opt/quanthedge

# 1. Python语法检查
/opt/quanthedge/venv/bin/python -m py_compile app.py
# 应该没有错误输出

# 2. 导入测试
/opt/quanthedge/venv/bin/python -c "from qh_command_tracer import get_tracer; print('Import OK')"
/opt/quanthedge/venv/bin/python -c "from qh_reconciliation_worker import ReconciliationWorker; print('Import OK')"

# 3. 检查Redis连接
redis-cli -n 3 PING
```

---

### 步骤7: 重启服务 (10分钟)

```bash
cd /opt/quanthedge

# 1. 保存环境变量
ps aux | grep 'uvicorn.*8090' | grep -v grep | head -1 | awk '{print $2}' | xargs -I {} cat /proc/{}/environ | tr '\0' '\n' > /tmp/qh_env_for_restart.txt

# 2. 停止旧进程
OLD_PID=$(ps aux | grep 'uvicorn.*8090' | grep -v grep | awk '{print $2}')
sudo kill $OLD_PID
sleep 3

# 3. 确认已停止
ps aux | grep 'uvicorn.*8090' | grep -v grep || echo "已停止"

# 4. 启动新进程
export $(cat /tmp/qh_env_for_restart.txt | xargs)
cd /opt/quanthedge
nohup /opt/quanthedge/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8090 --workers 1 > /tmp/qh_p0.log 2>&1 &

NEW_PID=$!
echo "新进程PID: $NEW_PID"
echo $NEW_PID > /tmp/qh.pid

# 5. 等待启动
sleep 5

# 6. 测试健康检查
curl -s http://127.0.0.1:8090/api/health | jq .

# 7. 检查日志
tail -50 /tmp/qh_p0.log
```

---

## 三、验证测试 (30分钟)

### 测试1: 追踪基础功能

```bash
# 1. 开仓测试(会返回command_id)
curl -X POST http://127.0.0.1:8090/api/cmd/open_pair \
  -H "Content-Type: application/json" \
  -H "x-license: QH-EBA405B9EFF03003" \
  -d '{
    "username":"no123",
    "symbol":"XAUUSD",
    "direction":"reverse",
    "slots":1,
    "confirm":true
  }'

# 应该返回包含 "command_id": "open_no123_XAUUSD_..." 的响应

# 2. 查询命令状态
COMMAND_ID="<从上面获取的command_id>"
curl -s http://127.0.0.1:8090/api/command/$COMMAND_ID | jq .

# 应该看到完整的追踪信息,包括latencies对象

# 3. 检查Redis中的数据
redis-cli -n 3 KEYS "qh:command:*" | head -5
redis-cli -n 3 HGETALL "qh:command:$COMMAND_ID"
```

### 测试2: 对账Worker运行状态

```bash
# 1. 检查Worker进程
ps aux | grep start_reconciliation_worker

# 2. 查看Worker日志
tail -f /tmp/reconciliation_worker.log

# 应该看到类似输出:
# 2026-07-23 17:40:00 [INFO] ReconciliationWorker started
# 2026-07-23 17:40:05 [INFO] 本轮对账: 0笔订单 (UNKNOWN:0, RECONCILING:0)

# 3. 手动创建一个UNKNOWN状态的测试命令
redis-cli -n 3 << REDIS
HSET qh:command:test_unknown_001 type open_pair
HSET qh:command:test_unknown_001 username no123
HSET qh:command:test_unknown_001 symbol XAUUSD
HSET qh:command:test_unknown_001 status UNKNOWN
HSET qh:command:test_unknown_001 api_received "2026-07-23T17:35:00Z"
HSET qh:command:test_unknown_001 main_ticket "999999"
HSET qh:command:test_unknown_001 hedge_ticket "888888"
EXPIRE qh:command:test_unknown_001 3600
REDIS

# 4. 等待5秒,观察Worker日志
# 应该看到Worker尝试对账这笔订单
```

### 测试3: 端到端延迟分析

```bash
# 1. 连续发起10笔开仓(确保entry_spread设置合理)
for i in {1..10}; do
  curl -s -X POST http://127.0.0.1:8090/api/cmd/open_pair \
    -H "Content-Type: application/json" \
    -H "x-license: QH-EBA405B9EFF03003" \
    -d '{
      "username":"no123",
      "symbol":"XAUUSD",
      "direction":"reverse",
      "slots":1,
      "confirm":true
    }' | jq -r '.command_id' >> /tmp/test_command_ids.txt
  sleep 10
done

# 2. 批量查询延迟数据
while read cmd_id; do
  echo "=== $cmd_id ==="
  curl -s http://127.0.0.1:8090/api/command/$cmd_id | jq '.latencies'
done < /tmp/test_command_ids.txt

# 3. 计算统计数据(可以用Python脚本)
python3 << PYEOF
import json
import requests

with open('/tmp/test_command_ids.txt') as f:
    cmd_ids = [line.strip() for line in f]

total_times = []
preflight_times = []

for cmd_id in cmd_ids:
    resp = requests.get(f'http://127.0.0.1:8090/api/command/{cmd_id}')
    if resp.status_code == 200:
        data = resp.json()
        latencies = data.get('latencies', {})
        if 'total_ms' in latencies:
            total_times.append(latencies['total_ms'])
        if 'preflight_ms' in latencies:
            preflight_times.append(latencies['preflight_ms'])

if total_times:
    print(f"总耗时: min={min(total_times):.1f}ms, max={max(total_times):.1f}ms, avg={sum(total_times)/len(total_times):.1f}ms")
if preflight_times:
    print(f"前置检查: min={min(preflight_times):.1f}ms, max={max(preflight_times):.1f}ms, avg={sum(preflight_times)/len(preflight_times):.1f}ms")
PYEOF
```

---

## 四、预期结果

### 成功标志

1. **服务启动正常**
   - curl http://127.0.0.1:8090/api/health 返回200
   - 日志中无import错误

2. **追踪功能工作**
   - 每笔开仓/平仓返回command_id
   - /api/command/{id} 可查询到完整信息
   - Redis中有qh:command:*键

3. **对账Worker运行**
   - ps能看到worker进程
   - 日志中有"ReconciliationWorker started"
   - 每5秒有"本轮对账"日志

4. **延迟数据可采集**
   - latencies对象包含preflight_ms, total_ms等字段
   - 数据合理(total_ms > preflight_ms)

### 如果失败

**回滚步骤**:
```bash
cd /opt/quanthedge

# 1. 停止新进程
sudo kill $(cat /tmp/qh.pid)

# 2. 恢复备份
cp app.py.bak_p0_20260723_173447 app.py

# 3. 重启原版本
# (按照步骤7的启动流程)
```

---

## 五、后续工作 (P0剩余部分)

完成上述基础追踪后,还需要:

1. **在Bridge添加order_send时间戳** (需要修改Bridge代码)
   - 记录ORDER_SEND_START_MAIN/HEDGE
   - 记录ORDER_SEND_END_MAIN/HEDGE

2. **完善对账逻辑**
   - 实现_check_position_in_db的实际DB查询
   - 添加飞书/邮件告警集成
   - 优化对账间隔和超时阈值

3. **实现202 UNKNOWN返回逻辑**
   - 修改order_send的超时处理
   - 前端适配202状态码

预计P0完整实施时间: **2-3天**

---

## 六、监控和维护

### 日常监控命令

```bash
# 查看追踪数据量
redis-cli -n 3 --scan --pattern "qh:command:*" | wc -l

# 查看UNKNOWN状态数量
curl -s http://127.0.0.1:8090/api/commands/unknown | jq '.count'

# 查看Worker状态
ps aux | grep reconciliation_worker
tail -20 /tmp/reconciliation_worker.log

# 清理过期追踪数据(手动)
redis-cli -n 3 --scan --pattern "qh:command:*" | xargs redis-cli -n 3 DEL
```

### 性能影响评估

- **Redis内存增长**: 每笔订单约1KB,1000笔=1MB,24小时自动过期
- **CPU开销**: 追踪记录<1ms,对账Worker空闲时<0.1% CPU
- **网络开销**: 对账查询约1KB/笔,每5秒最多100笔=20KB/s

**总体影响**: 可忽略(<1%性能损耗)

---

**文档版本**: P0-v1.0  
**编写时间**: 2026-07-23  
**预计实施时间**: 2-3小时手动集成 + 30分钟测试
