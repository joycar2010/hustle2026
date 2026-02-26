# Bybit MT5 订单 10015 错误修复总结

## 修复完成时间
2026-02-26 16:58 UTC

## 问题描述
在反向套利策略中点击「启用反向开仓」按钮时，Bybit MT5 订单失败，错误码 retcode=10015 (Invalid price)。

## 根本原因
Python 浮点数精度累积导致价格计算后出现超长小数位（如 `5184.030000000001`），不符合 MT5 XAUUSD.s 品种要求的 2 位小数精度。

## 已实施的修复

### 1. 套利策略价格计算精度处理
**文件**: `backend/app/services/arbitrage_strategy.py`

修复了 4 处价格计算：
- ✅ 反向套利开仓（第 128-129 行）
- ✅ 正向套利开仓（第 45-46 行）
- ✅ 反向套利平仓（第 213-214 行）
- ✅ 正向套利平仓（第 277-278 行）

**修复方式**: 在价格计算时立即进行精度处理
```python
# 修改前
bybit_buy_price = spread_data.bybit_quote.bid_price + 0.01

# 修改后
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

### 2. 订单执行器价格精度强化
**文件**: `backend/app/services/order_executor.py`

**修复位置**: execute_dual_order 函数（第 400-406 行）

**修复方式**: 对 Bybit 价格进行强制精度处理
```python
# 修改前
# Bybit MT5 price precision is handled by send_order via symbol_info.digits

# 修改后
# Bybit MT5 XAUUSD.s: 2 decimal places (强制精度处理，防止浮点数精度问题)
if bybit_price is not None:
    bybit_price = round(bybit_price, 2)
```

### 3. MT5 客户端日志增强
**文件**: `backend/app/services/mt5_client.py`

**修复位置**: send_order 函数（第 264-283 行）

**修复方式**: 增加日志记录，便于追踪价格处理过程
```python
# 新增日志
logger.info(f"MT5 symbol_info for {symbol}: digits={digits}, point={point}")
logger.warning(f"MT5 symbol_info not available for {symbol}, using default digits=2")
logger.warning(f"Price rounded: {original_price} -> {price} (digits={digits})")
```

## 修复效果

### 预期效果
1. ✅ 所有价格在计算时立即进行精度处理，避免浮点数精度累积
2. ✅ 订单执行器再次确保价格精度，双重保障
3. ✅ MT5 客户端增强日志，便于问题追踪
4. ✅ Bybit MT5 订单 10015 错误完全消除

### 影响范围
- ✅ 反向套利开仓/平仓
- ✅ 正向套利开仓/平仓
- ✅ 所有使用 execute_dual_order 的功能

### 不受影响的功能
- ✅ Binance 订单逻辑（已有精度处理）
- ✅ 手动交易功能
- ✅ 其他策略功能

## 验证步骤

### 1. 后端验证
```bash
# 检查后端是否正常运行
ps aux | grep uvicorn

# 查看日志
tail -f /tmp/backend.log | grep "MT5 symbol_info"
```

### 2. 前端验证
1. 访问 http://13.115.21.77:3000
2. 进入 StrategyPanel.vue 反向套利策略
3. 点击「启用反向开仓」按钮
4. 验证：
   - ✅ Binance 订单成功
   - ✅ Bybit 订单成功（无 10015 错误）
   - ✅ 任务状态正常

### 3. 价格精度验证
```python
# 在 Python 控制台验证价格计算
bid_price = 5184.02
buy_price = round(bid_price + 0.01, 2)
print(f"buy_price = {buy_price}")  # 应该输出: 5184.03
print(f"type = {type(buy_price)}")  # 应该输出: <class 'float'>
print(f"decimals = {len(str(buy_price).split('.')[-1])}")  # 应该输出: 2
```

## 技术细节

### 浮点数精度问题示例
```python
# 问题演示
>>> 5184.02 + 0.01
5184.030000000001  # 浮点数精度误差

# 修复后
>>> round(5184.02 + 0.01, 2)
5184.03  # 正确的 2 位小数
```

### 价格传递链路
1. **套利策略计算**: `bybit_buy_price = round(bid_price + 0.01, 2)` ✅
2. **订单执行器**: `bybit_price = round(bybit_price, 2)` ✅
3. **MT5 客户端**: `price = round(price, digits)` ✅

三层精度保障，确保价格格式正确。

## 相关文档
- [详细故障分析报告](BYBIT_MT5_PRICE_ERROR_ANALYSIS.md)
- [MT5 订单修复记录](BUGFIX_MT5_INVALID_PRICE.md)
- [手动交易功能说明](MANUAL_TRADING_FUNCTIONS_REPORT.md)

## 后续建议

### 1. 监控建议
- 监控 MT5 订单成功率
- 关注日志中的价格四舍五入警告
- 定期检查 spread 值是否存在异常精度

### 2. 代码优化建议
- 考虑创建通用的价格处理工具函数
- 添加价格合法性预校验
- 完善单元测试覆盖价格精度场景

### 3. 文档建议
- 更新开发文档，说明价格精度处理规范
- 添加浮点数精度问题的最佳实践指南

## 联系方式
如遇到问题，请查看：
- 后端日志: `/tmp/backend.log`
- 详细分析: `BYBIT_MT5_PRICE_ERROR_ANALYSIS.md`

---

**修复状态**: ✅ 已完成
**后端状态**: ✅ 已重启
**验证状态**: ⏳ 待用户验证

**修复工程师**: Claude Sonnet 4.6
**修复时间**: 2026-02-26 16:58 UTC
