# MT5限价单优化升级说明

## 优化概述

基于参考文档建议，对MT5限价单实现进行了全面优化，增强了参数校验、动态品种信息获取和错误重试机制。

## 主要优化内容

### 1. 动态品种信息获取

**优化前**：
```python
# 硬编码默认值
digits = 2
point = 0.01
```

**优化后**：
```python
# 动态获取品种信息
symbol_info = mt5.symbol_info(symbol)
digits = symbol_info.digits
point = symbol_info.point
volume_min = symbol_info.volume_min
volume_max = symbol_info.volume_max
volume_step = symbol_info.volume_step

# 确保品种可见（XAUUSD.s可能默认隐藏）
if not symbol_info.visible:
    mt5.symbol_select(symbol, True)
```

**优势**：
- 自动适配不同品种的精度要求
- 支持XAUUSD.s等隐藏品种的自动激活
- 获取准确的交易限制参数

### 2. 手数标准化处理

**新增功能**：
```python
# 按volume_step对齐手数
normalized_volume = round(volume / volume_step) * volume_step
# 强制执行最小/最大手数限制
normalized_volume = max(normalized_volume, volume_min)
normalized_volume = min(normalized_volume, volume_max)
```

**优势**：
- 防止retcode=10014（数量无效）错误
- 自动修正不符合步长的手数
- 确保手数在允许范围内

### 3. 价格范围校验

**新增XAUUSD.s专属校验**：
```python
if symbol.upper() == "XAUUSD.S":
    if normalized_price < 1000 or normalized_price > 5000:
        logger.error(f"XAUUSD.s price out of valid range: {normalized_price}")
        return {
            'retcode': 10015,  # Invalid price
            'comment': f'Price out of range: {normalized_price}'
        }
```

**优势**：
- 前置拦截异常价格
- 防止因极端价格导致的订单失败
- 提供明确的错误信息

### 4. 订单填充类型优化

**优化前**：
```python
# 限价单使用RETURN（允许部分成交）
type_filling = mt5.ORDER_FILLING_RETURN
```

**优化后**：
```python
# 套利策略使用FOK（全部成交或取消）
type_filling = mt5.ORDER_FILLING_FOK
```

**优势**：
- FOK确保订单全部成交或完全取消
- 防止部分成交破坏套利逻辑
- 更适合需要精确数量匹配的套利场景

### 5. 错误重试机制

**新增智能重试**：
```python
# 可重试错误：报价失效(10030)、流动性不足(10018)
retry_errors = [10030, 10018]
if result.retcode in retry_errors and retry_count < max_retry - 1:
    retry_count += 1
    logger.warning(f"Order failed with recoverable error | Retry: {retry_count}")
    continue
```

**优势**：
- 自动处理临时性错误
- 提高订单成功率
- 减少因网络波动导致的失败

### 6. 新增辅助方法

**get_latest_tick()**：
```python
def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
    """获取品种最新tick数据（bid, ask, last, time, volume）"""
    tick = mt5.symbol_info_tick(symbol)
    return {
        'symbol': symbol,
        'bid': tick.bid,
        'ask': tick.ask,
        'last': tick.last,
        'time': datetime.fromtimestamp(tick.time),
        'volume': tick.volume
    }
```

**get_latest_price()**：
```python
def get_latest_price(self, symbol: str) -> Optional[float]:
    """获取品种最新成交价（便捷方法）"""
    tick = self.get_latest_tick(symbol)
    return tick['last'] if tick else None
```

**用途**：
- 策略可以基于最新报价动态定价
- 避免限价单价格偏离市场过远
- 提供更灵活的定价策略

## 优化对比表

| 特性 | 优化前 | 优化后 |
|------|--------|--------|
| 品种信息 | 硬编码默认值 | 动态获取 |
| 手数校验 | 无 | volume_step对齐 + min/max限制 |
| 价格校验 | 仅精度处理 | 精度 + 范围校验 |
| 填充类型 | RETURN（部分成交） | FOK（全部或取消） |
| 错误重试 | 无 | 智能重试2次 |
| 报价获取 | 无 | 新增tick/price方法 |
| 品种激活 | 无 | 自动激活隐藏品种 |

## 错误处理增强

### 新增错误码处理

| 错误码 | 说明 | 处理方式 |
|--------|------|---------|
| 10015 | 价格无效 | 前置范围校验 + 精度标准化 |
| 10014 | 数量无效 | 手数对齐 + min/max限制 |
| 10030 | 报价失效 | 自动重试2次 |
| 10018 | 流动性不足 | 自动重试2次 |
| -2 | 重试耗尽 | 自定义错误码 |

## 使用示例

### 基础调用（自动标准化）
```python
# 原始参数会自动标准化
result = mt5_client.send_order(
    symbol="XAUUSD.s",
    order_type=mt5.ORDER_TYPE_BUY_LIMIT,
    volume=0.033,  # 会自动对齐到0.03
    price=5168.347,  # 会自动四舍五入到5168.35
    comment="Reverse arbitrage"
)
```

### 使用最新报价定价
```python
# 获取最新报价
latest_price = mt5_client.get_latest_price("XAUUSD.s")

# 基于最新报价定价（卖出限价单高于市场价）
sell_price = latest_price + 0.5

result = mt5_client.send_order(
    symbol="XAUUSD.s",
    order_type=mt5.ORDER_TYPE_SELL_LIMIT,
    volume=0.03,
    price=sell_price
)
```

## 日志增强

优化后的日志输出更详细：

```
INFO: MT5 symbol_info for XAUUSD.s: digits=2, point=0.01, volume_min=0.01, volume_max=100.0, volume_step=0.01
WARNING: Volume normalized: 0.033 -> 0.03
WARNING: Price normalized: 5168.347 -> 5168.35
INFO: Order sent successfully | Symbol: XAUUSD.s | Type: 2 | Price: 5168.35 | Volume: 0.03 | Order ID: 123456
```

## 兼容性说明

- 完全向后兼容现有调用方式
- 新增参数`max_retry`默认为2，可选配置
- 所有标准化处理对调用方透明
- 错误返回格式保持一致

## 测试建议

1. 测试XAUUSD.s限价单（验证品种激活和范围校验）
2. 测试非标准手数（如0.033）的自动对齐
3. 测试价格精度处理（如5168.347）
4. 测试重试机制（模拟10030错误）
5. 测试FOK填充类型的全部成交行为

## 相关文档

- [MT5_LIMIT_ORDER_PRICE_FIX.md](MT5_LIMIT_ORDER_PRICE_FIX.md) - 限价单价格规则修复
- [MT5_FINAL_FIX.md](MT5_FINAL_FIX.md) - MT5订单填充类型修复
- [ARBITRAGE_FIXES_VERIFICATION.md](ARBITRAGE_FIXES_VERIFICATION.md) - 套利策略修复验证

## 修改文件

- `backend/app/services/mt5_client.py`
  - 第233-410行：优化send_order方法
  - 第412-490行：新增get_latest_tick和get_latest_price方法
