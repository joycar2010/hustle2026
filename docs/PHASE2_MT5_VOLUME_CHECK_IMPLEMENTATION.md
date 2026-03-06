# Phase 2: MT5成交量检查 - 实施完成

## 实施日期
2026-03-06

## 功能概述
实现MT5订单实际成交量验证机制，通过查询MT5 deals历史来确认订单真实成交量，并在部分成交时发送WebSocket报警。

## 实施内容

### 1. 新增方法：`MT5Client.get_deals_by_ticket()`
**文件**: `backend/app/services/mt5_client.py`

**功能**: 根据订单ticket查询MT5成交记录（deals）

**实现**:
```python
def get_deals_by_ticket(self, ticket: int) -> list:
    """
    Get deals for a specific order ticket (for volume verification)

    查询最近5分钟内与指定ticket相关的所有成交记录
    返回包含volume、price、time等信息的deal列表
    """
```

**关键点**:
- 查询时间范围：最近5分钟（足够覆盖新订单）
- 通过`deal.order == ticket`过滤相关成交
- 返回deal的volume、price、symbol等关键信息

### 2. 新增方法：`OrderExecutorV2._check_mt5_filled_volume()`
**文件**: `backend/app/services/order_executor_v2.py`

**功能**: 检查MT5订单实际成交量并与预期对比

**实现**:
```python
async def _check_mt5_filled_volume(
    self,
    account: Account,
    ticket: int,
    expected_volume: float
) -> Dict[str, Any]:
    """
    返回:
    - actual_filled: 实际成交量（从deals累计）
    - expected: 预期成交量
    - is_partial_fill: 是否部分成交（<95%）
    - fill_ratio: 成交比例
    - deals_count: 成交记录数量
    """
```

**关键点**:
- 调用`get_deals_by_ticket()`获取所有成交记录
- 累计所有deal的volume得到实际成交量
- 计算成交比例：`actual_filled / expected_volume`
- 判断部分成交：实际成交量 < 预期的95%

### 3. 新增方法：`OrderExecutorV2._send_partial_fill_alert()`
**文件**: `backend/app/services/order_executor_v2.py`

**功能**: 通过WebSocket发送部分成交报警

**实现**:
```python
async def _send_partial_fill_alert(
    self,
    user_id: UUID,
    symbol: str,
    expected_qty: float,
    actual_qty: float,
    ticket: int
):
    """
    发送WebSocket消息类型: mt5_partial_fill_alert
    包含: symbol, expected_qty, actual_qty, unfilled_qty, fill_ratio, ticket
    """
```

**消息格式**:
```json
{
  "type": "mt5_partial_fill_alert",
  "data": {
    "symbol": "XAUUSD.s",
    "expected_qty": 1.0,
    "actual_qty": 0.5,
    "unfilled_qty": 0.5,
    "fill_ratio": 50.0,
    "ticket": 123456,
    "timestamp": 1709712345.678
  }
}
```

### 4. 增强：`_execute_bybit_market_buy()` 和 `_execute_bybit_market_sell()`
**文件**: `backend/app/services/order_executor_v2.py`

**修改内容**:
1. 在订单执行后增加0.3秒等待，确保MT5处理完deals
2. 调用`_check_mt5_filled_volume()`验证实际成交量
3. 如果部分成交且成交量<50%，发送报警
4. 根据实际成交量（而非API返回值）更新`total_filled`和`remaining`
5. 95%以上成交视为完全成交

**关键改进**:
```python
# 旧代码：依赖API返回的filled_qty
filled_qty = status.get("filled_qty", 0)

# 新代码：从MT5 deals验证实际成交量
volume_check = await self._check_mt5_filled_volume(account, ticket, remaining)
actual_filled = volume_check["actual_filled"]
```

## 技术细节

### 成交量验证流程
1. 下单到MT5（通过`place_bybit_order`）
2. 等待0.1秒（bybit_timeout）
3. 额外等待0.3秒让MT5处理deals
4. 查询MT5 deals历史获取实际成交量
5. 对比实际成交量与预期成交量
6. 如果部分成交且<50%，发送WebSocket报警
7. 根据实际成交量决定是否重试

### 部分成交判定标准
- **完全成交**: actual_filled >= expected * 0.95 (95%+)
- **部分成交**: actual_filled < expected * 0.95
- **严重部分成交**: actual_filled < expected * 0.5 (50%以下，触发报警)

### 重试机制
- 最多重试1次（`max_retries = 1`）
- 每次重试使用剩余数量：`remaining = quantity - actual_filled`
- 重试时仍会进行成交量验证

## 优势

### 1. 数据准确性
- 不依赖API返回值，直接从MT5 deals查询
- 避免API与实际成交不一致的问题
- 累计所有deal volume，确保完整性

### 2. 实时监控
- WebSocket实时推送部分成交报警
- 前端可立即响应并提示用户
- 包含详细的成交信息（ticket、比例、未成交量）

### 3. 风险控制
- 及时发现部分成交情况
- 避免单边持仓风险
- 为后续补单或手动干预提供依据

## 测试建议

### 1. 正常成交测试
- 下单后验证`actual_filled == expected`
- 确认不触发部分成交报警

### 2. 部分成交测试
- 使用小额订单或流动性差的时段
- 验证`actual_filled < expected`
- 确认WebSocket报警正确发送

### 3. 无成交测试
- 验证`actual_filled == 0`
- 确认系统正确处理无成交情况

### 4. 多次成交测试
- 验证deals累计逻辑正确
- 确认`deals_count > 1`时volume正确累加

## 监控指标

### 日志输出
```
MT5 partial fill warning: 0.5/1.0 Lot (ticket: 123456)
Warning: Bybit order not fully filled after 2 attempts. Filled: 0.8, Remaining: 0.2
```

### WebSocket消息
- 消息类型: `mt5_partial_fill_alert`
- 发送条件: 成交量 < 预期的50%
- 接收方: 用户个人WebSocket连接

## 后续优化建议

### 1. 补单机制（可选）
如果部分成交严重（<50%），可以考虑自动补单：
```python
if actual_filled < expected * 0.5:
    # 尝试补单剩余数量
    补单结果 = await self._fill_remaining_order(...)
```

### 2. 成交量统计
记录每个订单的成交比例，用于：
- 分析MT5流动性
- 优化下单策略
- 调整订单大小

### 3. 前端展示
在前端添加部分成交提示：
- 显示成交比例
- 高亮未完全成交的订单
- 提供手动补单按钮

## 风险评估

### 低风险
- 只是增加验证逻辑，不改变原有下单流程
- 即使验证失败，也不影响订单执行

### 注意事项
- 增加0.3秒等待可能略微延长执行时间
- 查询deals需要MT5连接正常
- WebSocket断开时报警无法送达（但会记录日志）

## 回滚方案
如果出现问题，可以：
1. 移除`_check_mt5_filled_volume()`调用
2. 恢复使用`check_bybit_order_status()`的返回值
3. 保留新增方法，不影响系统稳定性
