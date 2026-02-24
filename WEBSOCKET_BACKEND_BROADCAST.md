# WebSocket 后端广播任务实现文档

**日期**: 2026-02-24
**状态**: 已完成

## 概述

实现了两个后台任务，定期通过 WebSocket 向所有连接的客户端广播账户余额和风险指标数据，完全消除前端的轮询需求。

## 实现的广播任务

### 1. Account Balance Streamer（账户余额广播）

**文件**: `backend/app/tasks/broadcast_tasks.py`

**功能**:
- 每 10 秒自动获取所有活跃账户的聚合数据
- 通过 WebSocket 广播 `account_balance` 消息类型
- 仅在有活跃连接时执行（优化性能）

**数据结构**:
```python
{
    "type": "account_balance",
    "data": {
        "summary": {
            "total_assets": float,
            "available_balance": float,
            "net_assets": float,
            "frozen_assets": float,
            "margin_balance": float,
            "unrealized_pnl": float,
            "daily_pnl": float,
            "risk_ratio": float,
            "account_count": int,
            "position_count": int
        },
        "accounts": [...],
        "positions": [...],
        "failed_accounts": [...],
        "timestamp": str
    }
}
```

**广播间隔**: 10 秒

### 2. Risk Metrics Streamer（风险指标广播）

**文件**: `backend/app/tasks/broadcast_tasks.py`

**功能**:
- 每 30 秒自动获取风险指标数据
- 通过 WebSocket 广播 `risk_metrics` 消息类型
- 包含账户摘要和持仓信息

**数据结构**:
```python
{
    "type": "risk_metrics",
    "data": {
        "summary": {
            "total_assets": float,
            "net_assets": float,
            "unrealized_pnl": float,
            "risk_ratio": float,
            ...
        },
        "positions": [...],
        "timestamp": str
    }
}
```

**广播间隔**: 30 秒

## 技术实现

### 后台任务类设计

```python
class AccountBalanceStreamer:
    def __init__(self):
        self.running = False
        self.task = None
        self.interval = 10  # 10秒间隔

    async def start(self):
        """启动广播任务"""
        self.running = True
        self.task = asyncio.create_task(self._stream_loop())

    async def stop(self):
        """停止广播任务"""
        self.running = False
        if self.task:
            self.task.cancel()

    async def _stream_loop(self):
        """主循环：获取数据并广播"""
        while self.running:
            # 检查是否有活跃连接
            if manager.get_connection_count() == 0:
                await asyncio.sleep(self.interval)
                continue

            # 获取数据
            async with get_db_context() as db:
                # 查询活跃账户
                # 获取聚合数据
                # 广播数据

            await asyncio.sleep(self.interval)
```

### 应用生命周期集成

**文件**: `backend/app/main.py`

```python
from app.tasks.broadcast_tasks import account_balance_streamer, risk_metrics_streamer

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    await market_streamer.start()
    await account_balance_streamer.start()  # 新增
    await risk_metrics_streamer.start()     # 新增
    yield
    # 关闭
    await market_streamer.stop()
    await account_balance_streamer.stop()   # 新增
    await risk_metrics_streamer.stop()      # 新增
```

## 性能优化

### 1. 连接检查
```python
if manager.get_connection_count() == 0:
    await asyncio.sleep(self.interval)
    continue
```
- 没有客户端连接时跳过数据获取
- 节省数据库查询和API调用

### 2. 异常处理
```python
except Exception as e:
    logger.error(f"Error in stream: {str(e)}", exc_info=True)
    await asyncio.sleep(self.interval)
```
- 捕获所有异常，防止任务崩溃
- 记录详细错误日志
- 继续下一次循环

### 3. 数据库会话管理
```python
async with get_db_context() as db:
    # 数据库操作
```
- 使用上下文管理器自动管理会话
- 确保连接正确关闭

## 前端集成

前端组件已经实现了 WebSocket 监听，无需修改：

### AssetDashboard.vue
```javascript
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    updateAccountData(message.data)
  }
})
```

### AccountStatusPanel.vue
```javascript
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
})
```

### RiskDashboard.vue
```javascript
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'risk_metrics') {
    handleRiskMetricsUpdate(message.data)
  }
})
```

### useAlertMonitoring.js
```javascript
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    const accountData = {
      binance_net_asset: message.data.summary?.binance_net_asset || 0,
      bybit_mt5_net_asset: message.data.summary?.bybit_mt5_net_asset || 0,
      total_net_asset: message.data.summary?.total_assets || 0
    }
    notificationStore.checkAccountAlerts(accountData)
  }
})
```

## 测试验证

### 1. 启动验证
```bash
# 启动后端服务
cd backend
python -m app.main

# 查看日志确认任务启动
# 应该看到：
# Account balance streamer started (interval: 10s)
# Risk metrics streamer started (interval: 30s)
```

### 2. WebSocket 连接测试
```javascript
// 在浏览器控制台
// 打开 DevTools -> Network -> WS
// 应该看到每 10 秒收到 account_balance 消息
// 每 30 秒收到 risk_metrics 消息
```

### 3. 性能监控
- 检查 WebSocket 监控仪表板
- 确认消息速率正常（account_balance: 6/min, risk_metrics: 2/min）
- 验证没有连接时不产生数据库查询

## 配置选项

### 调整广播间隔

**Account Balance**:
```python
# backend/app/tasks/broadcast_tasks.py
class AccountBalanceStreamer:
    def __init__(self):
        self.interval = 10  # 修改此值（秒）
```

**Risk Metrics**:
```python
# backend/app/tasks/broadcast_tasks.py
class RiskMetricsStreamer:
    def __init__(self):
        self.interval = 30  # 修改此值（秒）
```

### 禁用特定广播

在 `main.py` 中注释掉相应的启动/停止调用：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    # await account_balance_streamer.start()  # 禁用账户余额广播
    await risk_metrics_streamer.start()
    yield
    # 关闭
    # await account_balance_streamer.stop()
    await risk_metrics_streamer.stop()
```

## 故障排查

### 问题：广播任务未启动
**检查**:
1. 查看应用启动日志
2. 确认 `lifespan` 函数正确调用
3. 检查是否有异常抛出

### 问题：前端未收到消息
**检查**:
1. WebSocket 连接是否建立（DevTools -> Network -> WS）
2. 后端日志是否有错误
3. 前端 `marketStore.lastMessage` 是否更新

### 问题：数据不准确
**检查**:
1. 数据库中账户状态（`is_active` 字段）
2. API 密钥是否有效
3. 后端日志中的错误信息

## 性能指标

### 预期负载
- **Account Balance**: 每 10 秒 1 次数据库查询 + N 个 API 调用（N = 活跃账户数）
- **Risk Metrics**: 每 30 秒 1 次数据库查询 + N 个 API 调用
- **WebSocket 消息**: 每分钟 8 条消息（6 + 2）

### 资源使用
- **CPU**: 低（异步 I/O，大部分时间在等待）
- **内存**: 低（每次循环后释放数据）
- **网络**: 中等（取决于账户数量和 API 响应大小）

## 未来优化

### 1. 增量更新
- 仅广播变化的数据
- 减少消息大小

### 2. 用户级广播
- 为每个用户单独广播其账户数据
- 提高安全性和隐私性

### 3. 消息压缩
- 对大型消息进行压缩
- 减少带宽使用

### 4. 智能间隔调整
- 根据市场活跃度动态调整间隔
- 交易时段缩短间隔，非交易时段延长间隔

## 总结

✅ **已完成**:
- Account Balance 每 10 秒广播
- Risk Metrics 每 30 秒广播
- 集成到应用生命周期
- 性能优化（连接检查、异常处理）
- 前端已准备好接收数据

✅ **效果**:
- 前端完全消除账户和风险数据的轮询
- 实时数据更新（10-30 秒延迟）
- 服务器负载可控
- 自动错误恢复

🎯 **下一步**:
- 部署到生产环境
- 监控性能指标
- 根据实际使用情况调整间隔
