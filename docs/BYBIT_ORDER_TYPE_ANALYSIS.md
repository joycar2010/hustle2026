# Bybit订单类型分析报告（修改后）

## 执行摘要

Bybit账号通过MT5终端下单，**已修改为纯Taker模式**：

### 关键发现
- ✅ **当前策略**：ORDER_TYPE_BUY / ORDER_TYPE_SELL（Market，Taker方式）
- ❌ **已取消**：ORDER_TYPE_BUY_LIMIT / ORDER_TYPE_SELL_LIMIT（Maker方式）

---

## 1. Bybit订单执行方式（修改后）

### 1.1 MT5订单类型映射

**文件位置**：`backend/app/services/order_executor.py`（第437-445行）

**修改后代码**：
```python
self.place_bybit_order(
    bybit_account,
    bybit_symbol,
    bybit_side,
    "Market",  # Always use Market orders for Bybit (Taker)
    str(bybit_quantity),
    None,  # Market orders don't need price
),
```

**订单类型说明**：
- `ORDER_TYPE_BUY`：市价买单（Taker）✅ 当前使用
- `ORDER_TYPE_SELL`：市价卖单（Taker）✅ 当前使用
- ~~`ORDER_TYPE_BUY_LIMIT`：限价买单（Maker）~~ ❌ 已取消
- ~~`ORDER_TYPE_SELL_LIMIT`：限价卖单（Maker）~~ ❌ 已取消

---

## 2. 订单类型汇总（修改后）

| 场景 | MT5订单类型 | Maker/Taker | 手续费率 |
|------|------------|-------------|---------|
| 所有订单 | ORDER_TYPE_BUY / SELL | Taker | ~0.06% |

---

## 3. 修改原因

### 3.1 与Binance策略对比

| 平台 | 订单类型 | Maker/Taker | 手续费率 | 成交保证 |
|------|---------|-------------|---------|---------|
| Binance | LIMIT | Maker | ~0.02% | ❌ 可能不成交 |
| Bybit | MARKET | Taker | ~0.06% | ✅ 保证成交 |

### 3.2 策略优势

1. **成交保证**
   - Bybit使用MARKET订单，保证立即成交
   - 避免单边持仓风险

2. **套利执行**
   - Binance挂单等待（Maker，低手续费）
   - Bybit立即成交（Taker，保证执行）
   - 平衡成本和执行速度

3. **风险控制**
   - 如果Binance订单成交，Bybit已经成交
   - 如果Binance订单不成交，可以取消Bybit对冲

---

## 4. 手续费影响

### 4.1 单次交易（1 XAU @ 2700 USDT）

**Binance（Maker）**：
- 手续费率：0.02%
- 单边手续费：2700 × 0.0002 = 0.54 USDT

**Bybit（Taker）**：
- 手续费率：0.06%
- 单边手续费：2700 × 0.0006 = 1.62 USDT

**总手续费（单边）**：0.54 + 1.62 = 2.16 USDT
**总手续费（双边）**：2.16 × 2 = 4.32 USDT

### 4.2 与之前策略对比

**修改前（Binance Maker + Bybit Maker）**：
- 最佳情况：1.08 USDT（双边）
- 最坏情况：2.16 USDT（双边，追单）

**修改后（Binance Maker + Bybit Taker）**：
- 固定成本：4.32 USDT（双边）

**成本增加**：4.32 - 1.08 = 3.24 USDT（300%）

---

## 5. 结论

**Bybit账号订单下单方式（修改后）**：
- ✅ **唯一方式**：MARKET订单（Taker）- 通过MT5的ORDER_TYPE_BUY/SELL
- ❌ **已取消**：LIMIT订单（Maker）

**策略特点**：
- Binance：Maker（低成本，可能不成交）
- Bybit：Taker（高成本，保证成交）
- 总体：混合策略，平衡成本和执行

**适用场景**：
- 适合快速套利，优先保证成交
- 不适合低利润套利（手续费占比高）
- 建议套利点差 > 5 USDT 时使用
