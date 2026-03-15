# 动态调整市场数据推送频率方案

## 需求分析

### 目标
- **有策略运行时**: 4次/秒（0.25秒间隔）- 高频更新确保策略及时响应
- **无策略运行时**: 1次/秒（1秒间隔）- 降低负载，节省资源

### 当前状态
- **MarketDataStreamer**: 固定1秒间隔推送市场数据
- **数据源**:
  - Binance: WebSocket实时流（binance_ws）
  - Bybit: MT5客户端直连（mt5_client.get_tick()）

## 可行性分析

### 1. MT5客户端性能

#### MT5 Tick获取特性
```python
# 当前实现（market_service.py）
tick = await loop.run_in_executor(None, self.mt5_client.get_tick, mt5_symbol)
```

**MT5性能评估**:
- ✅ **支持高频查询**: MT5 API可以支持毫秒级tick查询
- ✅ **本地连接**: MT5客户端直连，延迟极低（<10ms）
- ✅ **无API限制**: 不受交易所API rate limit限制
- ⚠️ **CPU开销**: 高频查询会增加CPU使用率
- ⚠️ **网络稳定性**: 依赖MT5客户端与服务器的连接质量

**结论**: MT5可以支持4次/秒的查询频率，技术上完全可行。

### 2. Binance WebSocket性能

**当前实现**:
- Binance使用WebSocket bookTicker流
- 实时推送，无需主动查询
- 数据存储在`binance_ws.bid`和`binance_ws.ask`

**性能评估**:
- ✅ **实时推送**: 数据自动更新，无查询开销
- ✅ **零延迟**: 直接读取内存中的最新数据
- ✅ **无限制**: 不受推送频率影响

**结论**: Binance WebSocket完全支持任意频率的读取。

### 3. 系统资源影响

#### 从1次/秒提升到4次/秒的影响

**CPU使用率**:
- MT5 tick查询: +5-10%
- 数据序列化: +2-3%
- WebSocket广播: +3-5%
- **总计**: 约+10-18% CPU使用率

**内存使用**:
- 影响极小（<1MB）
- 主要是临时对象创建

**网络带宽**:
- 每次推送约200-300字节
- 4次/秒 = 800-1200字节/秒
- **总计**: 约1KB/s（可忽略）

**数据库负载**:
- `store_spread_history()`写入频率增加4倍
- 建议：无策略时不写入历史，或降低写入频率

**结论**: 资源影响可控，主要是CPU略有增加。

## 实施方案

### 方案A：基于策略启用状态的动态调整（推荐）

#### 实现逻辑
```python
# backend/app/tasks/market_data.py

class MarketDataStreamer:
    def __init__(self):
        self.running = False
        self.task = None
        self.base_interval = 1.0  # 基础间隔（无策略时）
        self.active_interval = 0.25  # 活跃间隔（有策略时）
        self.current_interval = self.base_interval
        self.broadcast_count = 0
        self.last_broadcast_time = None
        self.error_count = 0

    async def _get_active_strategies_count(self) -> int:
        """获取当前启用的策略数量"""
        from app.core.database import get_db_context
        from app.models.strategy_config import StrategyConfig
        from sqlalchemy import select, or_

        try:
            async with get_db_context() as db:
                result = await db.execute(
                    select(StrategyConfig).where(
                        or_(
                            StrategyConfig.opening_enabled == True,
                            StrategyConfig.closing_enabled == True
                        )
                    )
                )
                configs = result.scalars().all()
                return len(configs)
        except Exception as e:
            logger.error(f"Failed to get active strategies: {e}")
            return 0

    async def _stream_loop(self):
        """主推送循环 - 动态调整频率"""
        logger.info("Market data streamer started with dynamic frequency")

        while self.running:
            try:
                # 检查是否有活跃策略
                active_count = await self._get_active_strategies_count()

                # 动态调整间隔
                if active_count > 0:
                    self.current_interval = self.active_interval  # 0.25s (4次/秒)
                else:
                    self.current_interval = self.base_interval  # 1s (1次/秒)

                # 获取市场数据
                spread_data = await market_data_service.get_current_spread(
                    use_cache=False
                )

                # 只在有策略时存储历史（降低数据库负载）
                if active_count > 0:
                    await market_data_service.store_spread_history(spread_data)

                # 广播到所有连接的客户端
                await manager.broadcast_market_data(spread_data.model_dump())
                self.broadcast_count += 1
                self.last_broadcast_time = datetime.now().isoformat()

                # 使用当前间隔等待
                await asyncio.sleep(self.current_interval)

            except Exception as e:
                logger.error(f"Error in market data stream: {str(e)}")
                self.error_count += 1
                await asyncio.sleep(self.current_interval)
```

#### 优点
- ✅ 自动检测策略状态
- ✅ 无需手动干预
- ✅ 实时调整频率
- ✅ 降低无策略时的资源消耗

#### 缺点
- ⚠️ 每次循环需要查询数据库（轻量级查询）
- ⚠️ 策略启用/禁用时有1秒延迟

### 方案B：基于WebSocket连接数的动态调整

#### 实现逻辑
```python
async def _stream_loop(self):
    """基于连接数动态调整"""
    while self.running:
        try:
            # 检查WebSocket连接数
            connection_count = manager.get_connection_count()

            # 有连接时使用高频，无连接时使用低频
            if connection_count > 0:
                self.current_interval = self.active_interval  # 0.25s
            else:
                self.current_interval = self.base_interval  # 1s

            # ... 其余逻辑相同
```

#### 优点
- ✅ 无需数据库查询
- ✅ 性能开销最小
- ✅ 响应速度快

#### 缺点
- ❌ 不够精确（有连接不代表有策略运行）
- ❌ 可能在无策略时仍使用高频

### 方案C：混合方案（最优）

#### 实现逻辑
```python
async def _stream_loop(self):
    """混合方案：连接数 + 策略状态"""
    check_interval_counter = 0
    cached_active_count = 0

    while self.running:
        try:
            # 每10次循环检查一次策略状态（降低数据库查询频率）
            if check_interval_counter % 10 == 0:
                cached_active_count = await self._get_active_strategies_count()
            check_interval_counter += 1

            # 决定推送频率
            connection_count = manager.get_connection_count()

            if connection_count > 0 and cached_active_count > 0:
                # 有连接且有策略：高频
                self.current_interval = self.active_interval  # 0.25s
            else:
                # 无连接或无策略：低频
                self.current_interval = self.base_interval  # 1s

            # 获取并推送数据
            spread_data = await market_data_service.get_current_spread(use_cache=False)

            # 只在有策略时存储历史
            if cached_active_count > 0:
                await market_data_service.store_spread_history(spread_data)

            await manager.broadcast_market_data(spread_data.model_dump())
            self.broadcast_count += 1
            self.last_broadcast_time = datetime.now().isoformat()

            await asyncio.sleep(self.current_interval)

        except Exception as e:
            logger.error(f"Error in market data stream: {str(e)}")
            self.error_count += 1
            await asyncio.sleep(self.current_interval)
```

#### 优点
- ✅ 精确检测（连接数 + 策略状态）
- ✅ 降低数据库查询频率（每10次循环查1次）
- ✅ 快速响应（连接数实时检测）
- ✅ 资源优化（无策略时不存储历史）

#### 缺点
- ⚠️ 实现稍复杂
- ⚠️ 策略状态变化有2.5秒延迟（10次 × 0.25s）

## 性能对比

### 资源消耗对比表

| 场景 | 推送频率 | CPU使用率 | 数据库写入 | 网络带宽 |
|------|---------|----------|-----------|---------|
| 当前（固定1次/秒） | 1次/秒 | 基准 | 1次/秒 | 0.3KB/s |
| 无策略（1次/秒） | 1次/秒 | 基准 | 0次/秒 | 0.3KB/s |
| 有策略（4次/秒） | 4次/秒 | +15% | 4次/秒 | 1.2KB/s |

### 优化收益

**无策略时段（假设占70%时间）**:
- CPU节省: 0%（已是1次/秒）
- 数据库写入减少: 70%（不存储历史）

**有策略时段（假设占30%时间）**:
- 响应速度提升: 4倍（0.25s vs 1s）
- 策略执行精度提升: 显著

**总体收益**:
- 数据库负载降低约70%
- 策略响应速度提升4倍
- CPU使用率略增（有策略时+15%，但仅占30%时间）

## 实施步骤

### Step 1: 修改MarketDataStreamer
**文件**: `backend/app/tasks/market_data.py`

1. 添加`active_interval`和`base_interval`属性
2. 实现`_get_active_strategies_count()`方法
3. 修改`_stream_loop()`实现动态频率调整
4. 添加条件判断是否存储历史

### Step 2: 添加监控指标
**文件**: `backend/app/tasks/market_data.py`

```python
def get_stats(self) -> dict:
    """获取推送统计信息"""
    return {
        "running": self.running,
        "current_interval": self.current_interval,
        "broadcast_count": self.broadcast_count,
        "error_count": self.error_count,
        "last_broadcast_time": self.last_broadcast_time,
        "frequency": f"{1/self.current_interval:.1f} times/sec"
    }
```

### Step 3: 添加API端点（可选）
**文件**: `backend/app/api/v1/system.py`

```python
@router.get("/market-streamer/stats")
async def get_market_streamer_stats():
    """获取市场数据推送器状态"""
    from app.tasks.market_data import market_streamer
    return market_streamer.get_stats()
```

### Step 4: 测试验证

1. **无策略测试**:
   - 禁用所有策略
   - 观察推送频率为1次/秒
   - 验证数据库无历史写入

2. **有策略测试**:
   - 启用任意策略
   - 观察推送频率提升到4次/秒
   - 验证数据库有历史写入

3. **切换测试**:
   - 启用/禁用策略
   - 观察频率动态调整
   - 验证延迟在可接受范围内

## 风险评估

### 低风险
- ✅ 不改变数据格式
- ✅ 向后兼容
- ✅ 可随时回滚

### 中风险
- ⚠️ MT5高频查询可能增加CPU负载
- ⚠️ 数据库查询可能影响性能

### 缓解措施
1. 使用缓存减少数据库查询频率
2. 监控CPU使用率，必要时调整频率
3. 添加降级机制（出错时回退到1次/秒）

## 推荐方案

**推荐使用方案C（混合方案）**，理由：
1. ✅ 精确检测策略状态
2. ✅ 降低数据库查询频率
3. ✅ 快速响应连接变化
4. ✅ 资源优化效果最佳
5. ✅ 实现复杂度可控

## 总结

### 可行性结论
**完全可行**。MT5客户端直连支持高频查询，Binance WebSocket无限制，系统资源影响可控。

### 预期效果
- 有策略时：响应速度提升4倍（0.25s vs 1s）
- 无策略时：数据库负载降低70%
- 总体：CPU使用率略增（+5%平均），但策略执行精度显著提升

### 实施建议
1. 先实施方案C（混合方案）
2. 添加监控指标观察效果
3. 根据实际运行情况微调参数
4. 考虑添加手动调频API（高级功能）
