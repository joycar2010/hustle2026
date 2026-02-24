# WebSocket 性能监控指南

**日期**: 2026-02-24
**目的**: 在生产环境中监控 WebSocket 性能和健康状况

## 概述

本指南提供了在生产环境中监控 WebSocket 系统的完整方案，包括关键指标、监控工具、告警规则和故障排查步骤。

## 关键性能指标 (KPIs)

### 1. 连接指标

#### 活跃连接数
```python
# 后端监控
from app.websocket.manager import manager

active_connections = manager.get_connection_count()
```

**正常范围**: 根据并发用户数
**告警阈值**:
- 警告: > 1000 连接
- 严重: > 5000 连接

#### 连接成功率
```
连接成功率 = 成功连接数 / 总连接尝试数 × 100%
```

**目标**: > 99%
**告警阈值**: < 95%

#### 平均连接时长
**目标**: > 30 分钟
**告警阈值**: < 5 分钟（频繁断开重连）

### 2. 消息指标

#### 消息吞吐量
- **Market Data**: 60 消息/分钟（每秒1条）
- **Account Balance**: 6 消息/分钟（每10秒1条）
- **Risk Metrics**: 2 消息/分钟（每30秒1条）
- **Order Updates**: 按需（交易时）

**总计**: ~70-100 消息/分钟/用户

#### 消息延迟
```
消息延迟 = 客户端接收时间 - 服务器发送时间
```

**目标**: < 100ms
**告警阈值**:
- 警告: > 500ms
- 严重: > 1000ms

#### 消息丢失率
```
消息丢失率 = 丢失消息数 / 总发送消息数 × 100%
```

**目标**: < 0.1%
**告警阈值**: > 1%

### 3. 系统资源指标

#### CPU 使用率
**正常范围**: < 50%
**告警阈值**:
- 警告: > 70%
- 严重: > 90%

#### 内存使用
**正常范围**: < 2GB（1000 连接）
**告警阈值**:
- 警告: > 4GB
- 严重: > 8GB

#### 网络带宽
**估算**: 每连接 ~10KB/s
**告警阈值**: 接近带宽上限的 80%

### 4. 错误指标

#### 错误率
```
错误率 = 错误数 / 总请求数 × 100%
```

**目标**: < 0.1%
**告警阈值**: > 1%

#### 重连次数
**正常**: < 5 次/小时/连接
**告警阈值**: > 20 次/小时/连接

## 监控实现

### 1. 前端监控

#### WebSocket 监控组件
已实现: `frontend/src/components/system/WebSocketMonitor.vue`

**功能**:
- 实时连接状态
- 消息统计（总数、速率、类型分布）
- 运行时间跟踪
- 最近消息日志

**访问**: 系统视图 → WebSocket 监控标签

#### 浏览器 DevTools
```javascript
// 在控制台监控 WebSocket
// 1. 打开 DevTools → Network → WS
// 2. 查看消息流
// 3. 检查连接状态
```

#### 自定义监控代码
```javascript
// frontend/src/stores/market.js
export const useMarketStore = defineStore('market', () => {
  const metrics = ref({
    totalMessages: 0,
    messagesByType: {},
    errors: 0,
    reconnections: 0,
    avgLatency: 0
  })

  // 在消息处理中更新指标
  function handleMessage(event) {
    metrics.value.totalMessages++

    const message = JSON.parse(event.data)
    metrics.value.messagesByType[message.type] =
      (metrics.value.messagesByType[message.type] || 0) + 1

    // 计算延迟
    if (message.timestamp) {
      const latency = Date.now() - new Date(message.timestamp).getTime()
      metrics.value.avgLatency =
        (metrics.value.avgLatency * 0.9) + (latency * 0.1)
    }
  }

  return { metrics, ... }
})
```

### 2. 后端监控

#### 日志记录
```python
# backend/app/websocket/manager.py
import logging
import time

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.metrics = {
            'total_connections': 0,
            'total_messages': 0,
            'errors': 0,
            'start_time': time.time()
        }

    async def connect(self, websocket: WebSocket, user_id: str = None):
        self.metrics['total_connections'] += 1
        logger.info(f"New connection: user_id={user_id}, total={self.get_connection_count()}")
        await websocket.accept()
        # ...

    async def broadcast(self, message: dict):
        start_time = time.time()
        self.metrics['total_messages'] += 1

        # ... broadcast logic ...

        duration = time.time() - start_time
        if duration > 0.1:  # 超过100ms记录警告
            logger.warning(f"Slow broadcast: {duration:.3f}s")
```

#### Prometheus 指标
```python
# backend/app/monitoring/metrics.py
from prometheus_client import Counter, Gauge, Histogram

# 连接指标
websocket_connections = Gauge(
    'websocket_active_connections',
    'Number of active WebSocket connections'
)

# 消息指标
websocket_messages_total = Counter(
    'websocket_messages_total',
    'Total number of WebSocket messages sent',
    ['message_type']
)

# 延迟指标
websocket_broadcast_duration = Histogram(
    'websocket_broadcast_duration_seconds',
    'Time spent broadcasting messages'
)

# 错误指标
websocket_errors_total = Counter(
    'websocket_errors_total',
    'Total number of WebSocket errors',
    ['error_type']
)
```

#### 健康检查端点
```python
# backend/app/api/v1/system.py
from fastapi import APIRouter
from app.websocket.manager import manager

router = APIRouter()

@router.get("/health/websocket")
async def websocket_health():
    """WebSocket health check endpoint"""
    connection_count = manager.get_connection_count()

    return {
        "status": "healthy" if connection_count >= 0 else "unhealthy",
        "active_connections": connection_count,
        "uptime_seconds": time.time() - manager.metrics['start_time'],
        "total_messages": manager.metrics['total_messages'],
        "error_count": manager.metrics['errors']
    }
```

### 3. 第三方监控工具

#### Grafana 仪表板
```yaml
# grafana-dashboard.json
{
  "dashboard": {
    "title": "WebSocket Performance",
    "panels": [
      {
        "title": "Active Connections",
        "targets": [{
          "expr": "websocket_active_connections"
        }]
      },
      {
        "title": "Message Rate",
        "targets": [{
          "expr": "rate(websocket_messages_total[1m])"
        }]
      },
      {
        "title": "Broadcast Latency",
        "targets": [{
          "expr": "histogram_quantile(0.95, websocket_broadcast_duration_seconds)"
        }]
      },
      {
        "title": "Error Rate",
        "targets": [{
          "expr": "rate(websocket_errors_total[5m])"
        }]
      }
    ]
  }
}
```

#### Sentry 错误追踪
```python
# backend/app/main.py
import sentry_sdk

sentry_sdk.init(
    dsn="YOUR_SENTRY_DSN",
    traces_sample_rate=0.1,
    profiles_sample_rate=0.1,
)

# 在 WebSocket 错误处理中
try:
    await manager.broadcast(message)
except Exception as e:
    sentry_sdk.capture_exception(e)
    logger.error(f"Broadcast error: {e}")
```

## 告警规则

### 1. 连接告警

#### 连接数异常
```yaml
# Prometheus Alert Rules
groups:
  - name: websocket_alerts
    rules:
      - alert: HighConnectionCount
        expr: websocket_active_connections > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High WebSocket connection count"
          description: "{{ $value }} active connections"

      - alert: NoConnections
        expr: websocket_active_connections == 0
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "No active WebSocket connections"
```

#### 频繁重连
```yaml
      - alert: FrequentReconnections
        expr: rate(websocket_connections_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Frequent WebSocket reconnections"
```

### 2. 性能告警

#### 高延迟
```yaml
      - alert: HighBroadcastLatency
        expr: histogram_quantile(0.95, websocket_broadcast_duration_seconds) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High WebSocket broadcast latency"
          description: "P95 latency: {{ $value }}s"
```

#### 消息积压
```yaml
      - alert: MessageBacklog
        expr: websocket_pending_messages > 1000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "WebSocket message backlog"
```

### 3. 错误告警

#### 高错误率
```yaml
      - alert: HighErrorRate
        expr: rate(websocket_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High WebSocket error rate"
          description: "{{ $value }} errors/sec"
```

## 性能优化建议

### 1. 连接优化

#### 连接池管理
```python
# 限制每个用户的连接数
MAX_CONNECTIONS_PER_USER = 5

async def connect(self, websocket: WebSocket, user_id: str):
    if user_id:
        user_connections = len(self.active_connections.get(user_id, set()))
        if user_connections >= MAX_CONNECTIONS_PER_USER:
            await websocket.close(code=1008, reason="Too many connections")
            return
    # ...
```

#### 心跳机制
```python
# 定期发送 ping 保持连接活跃
async def send_ping(self):
    while True:
        await asyncio.sleep(30)
        for connection in self.all_connections:
            try:
                await connection.send_json({"type": "ping"})
            except:
                pass
```

### 2. 消息优化

#### 消息批处理
```python
# 批量发送消息减少网络开销
async def broadcast_batch(self, messages: List[dict]):
    batch_message = {
        "type": "batch",
        "messages": messages
    }
    await self.broadcast(batch_message)
```

#### 消息压缩
```python
import gzip
import json

async def send_compressed(self, message: dict, websocket: WebSocket):
    json_str = json.dumps(message)
    compressed = gzip.compress(json_str.encode())
    await websocket.send_bytes(compressed)
```

### 3. 资源优化

#### 内存管理
```python
# 限制消息历史大小
MAX_MESSAGE_HISTORY = 100

def add_to_history(self, message: dict):
    self.message_history.append(message)
    if len(self.message_history) > MAX_MESSAGE_HISTORY:
        self.message_history.pop(0)
```

#### 连接清理
```python
# 定期清理断开的连接
async def cleanup_stale_connections(self):
    while True:
        await asyncio.sleep(60)
        stale = []
        for connection in self.all_connections:
            if connection.client_state == WebSocketState.DISCONNECTED:
                stale.append(connection)

        for connection in stale:
            self.disconnect(connection)
```

## 故障排查

### 问题 1: 连接频繁断开

**症状**: 客户端每隔几分钟就断开重连

**可能原因**:
1. 负载均衡器超时设置过短
2. 网络不稳定
3. 服务器资源不足

**排查步骤**:
```bash
# 1. 检查服务器日志
tail -f /var/log/app/websocket.log | grep "disconnect"

# 2. 检查负载均衡器配置
# Nginx 示例
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;

# 3. 检查服务器资源
top
free -h
netstat -an | grep ESTABLISHED | wc -l
```

**解决方案**:
- 增加负载均衡器超时时间
- 实现心跳机制
- 优化服务器资源

### 问题 2: 消息延迟高

**症状**: 消息从发送到接收延迟超过 1 秒

**可能原因**:
1. 服务器负载过高
2. 数据库查询慢
3. 网络拥塞

**排查步骤**:
```python
# 添加性能日志
import time

async def broadcast(self, message: dict):
    start = time.time()

    # 数据库查询时间
    db_start = time.time()
    data = await fetch_data()
    db_time = time.time() - db_start

    # 广播时间
    broadcast_start = time.time()
    await self._do_broadcast(message)
    broadcast_time = time.time() - broadcast_start

    total_time = time.time() - start

    logger.info(f"Timing: db={db_time:.3f}s, broadcast={broadcast_time:.3f}s, total={total_time:.3f}s")
```

**解决方案**:
- 优化数据库查询（添加索引、使用缓存）
- 减少广播频率
- 使用消息队列异步处理

### 问题 3: 内存泄漏

**症状**: 服务器内存使用持续增长

**可能原因**:
1. 连接未正确清理
2. 消息历史无限增长
3. 事件监听器未移除

**排查步骤**:
```python
# 使用 memory_profiler
from memory_profiler import profile

@profile
async def broadcast(self, message: dict):
    # ... 广播逻辑 ...
    pass

# 检查对象引用
import gc
import sys

def check_references():
    for obj in gc.get_objects():
        if isinstance(obj, WebSocket):
            print(f"WebSocket refs: {sys.getrefcount(obj)}")
```

**解决方案**:
- 确保 `disconnect()` 正确清理资源
- 限制消息历史大小
- 使用弱引用

## 性能基准测试

### 负载测试脚本
```python
# tests/load/websocket_load_test.py
import asyncio
import websockets
import time

async def connect_client(client_id: int):
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as websocket:
        start_time = time.time()
        message_count = 0

        while time.time() - start_time < 60:  # 运行 1 分钟
            message = await websocket.recv()
            message_count += 1

        return message_count

async def load_test(num_clients: int):
    tasks = [connect_client(i) for i in range(num_clients)]
    results = await asyncio.gather(*tasks)

    total_messages = sum(results)
    avg_messages = total_messages / num_clients

    print(f"Clients: {num_clients}")
    print(f"Total messages: {total_messages}")
    print(f"Avg messages/client: {avg_messages:.2f}")
    print(f"Messages/sec: {total_messages / 60:.2f}")

# 运行测试
asyncio.run(load_test(100))  # 100 个并发客户端
```

### 预期性能
- **100 并发连接**: < 50% CPU, < 500MB 内存
- **1000 并发连接**: < 80% CPU, < 2GB 内存
- **消息延迟**: P95 < 100ms, P99 < 200ms
- **吞吐量**: > 10,000 消息/秒

## 监控检查清单

### 日常检查（每天）
- [ ] 检查活跃连接数
- [ ] 检查错误日志
- [ ] 验证消息速率正常
- [ ] 检查服务器资源使用

### 每周检查
- [ ] 审查性能趋势
- [ ] 检查告警历史
- [ ] 验证备份和恢复流程
- [ ] 更新监控仪表板

### 每月检查
- [ ] 进行负载测试
- [ ] 审查和优化查询
- [ ] 更新文档
- [ ] 培训团队成员

## 总结

有效的 WebSocket 监控需要：

1. **全面的指标收集**: 连接、消息、性能、错误
2. **实时监控工具**: Grafana、Prometheus、Sentry
3. **智能告警规则**: 及时发现问题
4. **定期性能测试**: 确保系统可扩展
5. **完善的故障排查流程**: 快速解决问题

通过遵循本指南，您可以确保 WebSocket 系统在生产环境中稳定、高效地运行。
