# MT5 订单 10015 错误最终修复方案

## 修复时间
2026-02-26 17:48 UTC

## 问题描述
Bybit MT5 限价单持续返回 `retcode=10015, comment=Invalid price` 错误，即使已经对价格进行了精度处理。

## 根本原因分析

经过深入分析，发现问题不仅仅是价格精度，还包括 **MT5 订单填充类型（type_filling）不匹配**：

### 问题 1: 价格精度（已修复）
- Python 浮点数运算可能产生超长小数位
- 已在多个层级添加 `round(price, 2)` 处理

### 问题 2: 订单填充类型不匹配（新发现）
**关键问题**: 所有订单（包括限价单）都使用 `ORDER_FILLING_IOC` (Immediate or Cancel)

**MT5 规则**:
- **限价单（PENDING 订单）**: 应使用 `ORDER_FILLING_RETURN`
- **市价单（DEAL 订单）**: 可以使用 `ORDER_FILLING_IOC`

**错误代码** (`mt5_client.py:303`):
```python
request = {
    "action": trade_action,
    "symbol": symbol,
    "volume": volume,
    "type": order_type,
    "deviation": deviation,
    "magic": self.login,
    "comment": comment,
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,  # ❌ 所有订单都用 IOC
}
```

## 最终修复方案

### 修改文件
**文件**: `backend/app/services/mt5_client.py`
**位置**: 第 285-304 行

**修改内容**:
```python
# 修改前
if order_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT, ...]:
    trade_action = mt5.TRADE_ACTION_PENDING
else:
    trade_action = mt5.TRADE_ACTION_DEAL

request = {
    ...
    "type_filling": mt5.ORDER_FILLING_IOC,  # ❌ 固定使用 IOC
}

# 修改后
if order_type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT, ...]:
    trade_action = mt5.TRADE_ACTION_PENDING
    type_filling = mt5.ORDER_FILLING_RETURN  # ✅ 限价单用 RETURN
else:
    trade_action = mt5.TRADE_ACTION_DEAL
    type_filling = mt5.ORDER_FILLING_IOC     # ✅ 市价单用 IOC

request = {
    ...
    "type_filling": type_filling,  # ✅ 动态选择
}
```

## MT5 订单填充类型说明

| 填充类型 | 适用订单类型 | 说明 |
|---------|------------|------|
| `ORDER_FILLING_RETURN` | 限价单（PENDING） | 订单可以部分成交，未成交部分保留在订单簿中 |
| `ORDER_FILLING_IOC` | 市价单（DEAL） | 立即成交或取消，不保留未成交部分 |
| `ORDER_FILLING_FOK` | 市价单（DEAL） | 全部成交或全部取消 |

## 已应用的所有修复

### 1. 价格精度修复
- ✅ `arbitrage_strategy.py`: 所有价格计算添加 `round(price, 2)`
- ✅ `order_executor.py`: Bybit 价格强制精度处理
- ✅ `mt5_client.py`: 价格精度日志记录

### 2. 订单填充类型修复（新）
- ✅ `mt5_client.py`: 根据订单类型动态选择填充类型
  - 限价单 → `ORDER_FILLING_RETURN`
  - 市价单 → `ORDER_FILLING_IOC`

### 3. 订单动作类型修复（已完成）
- ✅ `mt5_client.py`: 根据订单类型选择动作
  - 限价单 → `TRADE_ACTION_PENDING`
  - 市价单 → `TRADE_ACTION_DEAL`

## 验证步骤

### 1. 重启后端
```bash
taskkill //F //IM python.exe //T
cd /c/app/hustle2026/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 测试反向套利策略
1. 登录 http://13.115.21.77:3000 (admin/admin123)
2. 进入 StrategyPanel.vue
3. 点击「启用反向开仓」按钮
4. 验证：
   - ✅ Binance 订单成功
   - ✅ Bybit 订单成功（无 10015 错误）

### 3. 查看日志
```bash
tail -f /tmp/backend.log | grep -E "retcode|Invalid price|MT5 order"
```

## 技术细节

### MT5 限价单要求
1. **动作类型**: `TRADE_ACTION_PENDING`
2. **填充类型**: `ORDER_FILLING_RETURN`
3. **价格精度**: 必须符合品种要求（XAUUSD.s = 2 位小数）
4. **时间类型**: `ORDER_TIME_GTC` (Good Till Cancel)

### 完整的 MT5 限价单请求示例
```python
request = {
    "action": mt5.TRADE_ACTION_PENDING,      # 挂单动作
    "symbol": "XAUUSD.s",                    # 交易品种
    "volume": 0.01,                          # 交易量（Lot）
    "type": mt5.ORDER_TYPE_BUY_LIMIT,        # 限价买单
    "price": 5174.29,                        # 限价（2 位小数）
    "deviation": 10,                         # 价格偏差
    "magic": 123456,                         # 魔术数字
    "comment": "Reverse arbitrage open",     # 订单备注
    "type_time": mt5.ORDER_TIME_GTC,         # 有效期类型
    "type_filling": mt5.ORDER_FILLING_RETURN # 填充类型（关键！）
}
```

## 预期效果

修复后，MT5 限价单应该：
1. ✅ 正确使用 `TRADE_ACTION_PENDING` 动作
2. ✅ 正确使用 `ORDER_FILLING_RETURN` 填充类型
3. ✅ 价格精度符合 2 位小数要求
4. ✅ 成功下单，无 10015 错误

## 相关文档

- [MT5 价格错误详细分析](BYBIT_MT5_PRICE_ERROR_ANALYSIS.md)
- [前端端口修复](FRONTEND_PORT_FIX.md)
- [服务重启报告](SERVICE_RESTART_REPORT.md)

## 故障排查

如果仍然出现 10015 错误：

### 1. 检查 MT5 连接
```python
import MetaTrader5 as mt5
mt5.initialize()
print(f"MT5 version: {mt5.version()}")
print(f"Terminal info: {mt5.terminal_info()}")
```

### 2. 检查品种信息
```python
symbol_info = mt5.symbol_info("XAUUSD.s")
print(f"Digits: {symbol_info.digits}")
print(f"Point: {symbol_info.point}")
print(f"Filling modes: {symbol_info.filling_mode}")
```

### 3. 测试订单
```python
request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "XAUUSD.s",
    "volume": 0.01,
    "type": mt5.ORDER_TYPE_BUY_LIMIT,
    "price": 5174.29,
    "type_filling": mt5.ORDER_FILLING_RETURN,
    "type_time": mt5.ORDER_TIME_GTC,
}
result = mt5.order_send(request)
print(f"Retcode: {result.retcode}, Comment: {result.comment}")
```

---

**修复状态**: ✅ 已完成
**后端状态**: ✅ 已重启
**预期结果**: MT5 10015 错误应该完全消除
