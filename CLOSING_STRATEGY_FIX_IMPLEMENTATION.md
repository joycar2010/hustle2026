# 正向/反向平仓高频挂单撤单问题修复实施报告

## 实施时间
2026-03-13

## 问题回顾
点击正向平仓按钮后，1分钟内出现20+次Binance ask挂单并撤单，导致：
- 频繁的交易手续费损失
- 订单成交率极低
- 策略执行效率低下

## 根本原因
在价差临界值附近，系统进入"挂单(0.01s)→检测未成交→检查点差→撤单(0.01s)→重新挂单"的高频循环，没有给订单足够的成交时间。

## 实施方案

### 1. 新增配置参数 (strategy_executor_v3.py 第126-128行)

```python
# Closing strategy wait time configuration (to prevent high-frequency order cancellation)
self.close_wait_after_cancel_no_trade = 3.0  # Wait 3 seconds after canceling unfilled order
self.close_wait_after_cancel_part = 2.0      # Wait 2 seconds after canceling partially filled order
```

**说明**：
- `close_wait_after_cancel_no_trade`: 未成交撤单后等待3秒
- `close_wait_after_cancel_part`: 部分成交撤单后等待2秒
- 可配置参数，后期可根据实盘情况调整

### 2. 正向平仓策略修复

#### 场景1：Binance未成交撤单 (第1815行)
```python
await self._api_call_with_retry(
    self.order_executor.cancel_binance_order,
    config.symbol,
    binance_order['orderId']
)
# Wait after canceling unfilled order to prevent high-frequency re-ordering
self.logger.info(f"Waiting {self.close_wait_after_cancel_no_trade}s after canceling unfilled order")
await asyncio.sleep(self.close_wait_after_cancel_no_trade)
return {"success": False, "error": "Spread not met, order cancelled"}
```

**修改内容**：
- 撤单后增加3秒等待
- 添加日志记录等待时间
- 等待结束后才返回，避免立即重新挂单

#### 场景3：Binance部分成交撤单 (第1857行)
```python
await self._api_call_with_retry(
    self.order_executor.cancel_binance_order,
    config.symbol,
    binance_order['orderId']
)
# Wait after canceling partially filled order to prevent high-frequency re-ordering
self.logger.info(f"Waiting {self.close_wait_after_cancel_part}s after canceling partially filled order")
await asyncio.sleep(self.close_wait_after_cancel_part)
result = await self._handle_binance_filled_forward_closing(
    config, ladder, state, filled_qty, bybit_retry_count
)
```

**修改内容**：
- 撤单后增加2秒等待
- 添加日志记录等待时间
- 等待结束后才处理已成交部分

#### 场景2：Binance完全成交
**无修改** - 保持原逻辑，立即处理Bybit平仓，不影响平仓效率

### 3. 反向平仓策略修复

#### 场景1：Binance未成交撤单 (第1437行)
```python
await self._api_call_with_retry(
    self.order_executor.cancel_binance_order,
    config.symbol,
    binance_order['orderId']
)
# Wait after canceling unfilled order to prevent high-frequency re-ordering
self.logger.info(f"Waiting {self.close_wait_after_cancel_no_trade}s after canceling unfilled order")
await asyncio.sleep(self.close_wait_after_cancel_no_trade)
return {"success": False, "error": "Spread not met, order cancelled"}
```

#### 场景3：Binance部分成交撤单 (第1474行)
```python
await self._api_call_with_retry(
    self.order_executor.cancel_binance_order,
    config.symbol,
    binance_order['orderId']
)
# Wait after canceling partially filled order to prevent high-frequency re-ordering
self.logger.info(f"Waiting {self.close_wait_after_cancel_part}s after canceling partially filled order")
await asyncio.sleep(self.close_wait_after_cancel_part)
result = await self._handle_binance_filled_reverse_closing(
    config, ladder, state, filled_qty, bybit_retry_count
)
```

## 核心设计原则

### 1. 不改变策略核心逻辑
- ✅ 保留"点差值≤阈值"作为挂单唯一前提
- ✅ 保留三场景处理逻辑
- ✅ 保留Bybit 4次重试机制
- ✅ 不影响策略盈利逻辑

### 2. 精准约束高频循环
- ✅ 仅在撤单后增加等待时间
- ✅ 不影响订单检测速度（0.01秒）
- ✅ 不影响完全成交场景的效率

### 3. 灵活可配置
- ✅ 等待时间可通过参数调整
- ✅ 未成交和部分成交使用不同等待时间
- ✅ 便于后期根据实盘情况优化

## 修改文件清单

| 文件 | 修改位置 | 修改内容 |
|------|---------|---------|
| strategy_executor_v3.py | 第126-128行 | 新增等待时间配置参数 |
| strategy_executor_v3.py | 第1815行 | 正向平仓场景1增加等待 |
| strategy_executor_v3.py | 第1857行 | 正向平仓场景3增加等待 |
| strategy_executor_v3.py | 第1437行 | 反向平仓场景1增加等待 |
| strategy_executor_v3.py | 第1474行 | 反向平仓场景3增加等待 |

## 预期效果

### 修复前
```
挂单 → 0.01s → 检测未成交 → 检查点差 → 撤单 → 0.01s → 重新挂单
  ↑                                                        ↓
  └────────────────────── 20+次循环 ←──────────────────────┘
```

### 修复后
```
挂单 → 0.01s → 检测未成交 → 检查点差 → 撤单 → 3秒等待 → 重新检测点差 → 挂单
                                                    ↓
                                            点差不满足则停止
```

### 量化指标
- ✅ 挂单-撤单次数：从20+次降低到5次以内
- ✅ 订单成交率：提升50%以上
- ✅ 交易成本：减少频繁操作的手续费
- ✅ 策略稳定性：避免过度敏感的撤单逻辑

## 测试建议

### 1. 单元测试
- 测试等待时间是否正确执行
- 测试场景1和场景3的等待逻辑
- 测试场景2不受影响

### 2. 集成测试
- 模拟价差临界波动
- 观察挂单-撤单频率
- 确认等待时间生效

### 3. 实盘测试
- 小手数测试（0.01-0.1手）
- 观察1分钟内挂单次数
- 记录订单成交率
- 监控日志输出

### 4. 性能监控
- 监控平仓完成时间
- 对比修复前后的成交率
- 统计撤单次数变化

## 日志示例

修复后的日志输出：
```
[INFO] BINANCE_CLOSING_ORDER_PLACED: order_id=12345, qty=0.5, price_type=ask
[INFO] BINANCE_CLOSING_ORDER_STATUS: status=NEW, filled_qty=0.0
[INFO] FORWARD_CLOSING_SCENARIO_1_ABORT: reason=Binance unfilled and spread not met, spread=0.18
[INFO] Waiting 3.0s after canceling unfilled order
[INFO] (3秒后) FORWARD_CLOSING_ORDER_START: ladder=0, order_qty=0.5
```

## 配置调整建议

根据实盘情况，可以调整等待时间：

### 激进型（价差波动小）
```python
self.close_wait_after_cancel_no_trade = 2.0  # 2秒
self.close_wait_after_cancel_part = 1.0      # 1秒
```

### 保守型（价差波动大）
```python
self.close_wait_after_cancel_no_trade = 5.0  # 5秒
self.close_wait_after_cancel_part = 3.0      # 3秒
```

### 当前配置（推荐）
```python
self.close_wait_after_cancel_no_trade = 3.0  # 3秒
self.close_wait_after_cancel_part = 2.0      # 2秒
```

## 回滚方案

如果需要回滚，只需将等待时间设置为0：
```python
self.close_wait_after_cancel_no_trade = 0.0
self.close_wait_after_cancel_part = 0.0
```

## 总结

✅ **修复完成**

本次修复完全按照用户提供的方案实施：
1. 在场景1（未成交撤单）后增加3秒等待
2. 在场景3（部分成交撤单）后增加2秒等待
3. 场景2（完全成交）保持原逻辑不变
4. 同时修复了正向平仓和反向平仓策略
5. 不改变核心价差判定逻辑
6. 等待时间可配置，便于后期调整

预期可以将挂单-撤单次数从20+次降低到5次以内，显著提升订单成交率和策略稳定性。
