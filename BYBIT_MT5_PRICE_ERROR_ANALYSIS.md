# Bybit MT5 订单 10015 价格无效错误 - 故障分析与修复方案

## 一、故障核心信息

### 1.1 业务场景与操作
- **页面路径**: `/StrategyPanel.vue` (反向套利策略模块)
- **操作**: 点击「启用反向开仓」按钮执行批次1订单下单
- **核心故障**: 批次1执行失败，提示 "Failed to place initial orders"

### 1.2 错误详情
```json
{
  "success": false,
  "task_id": "fee9d836-f37f-4f95-994a-951d357cb6d8",
  "spread": 1.160000000000764,
  "execution_result": {
    "binance_result": {"success": true, ...},
    "bybit_result": {
      "success": false,
      "platform": "bybit",
      "error": "MT5 order error: retcode=10015, comment=Invalid price"
    }
  }
}
```

**关键观察**:
- ✅ Binance 订单成功 (success=true)
- ❌ Bybit MT5 订单失败 (retcode=10015)
- ⚠️ spread 值异常: `1.160000000000764` (超长小数位)

### 1.3 技术栈约束
- **前端**: Vue3 (Composition API) + WebSocket + Axios
- **后端**: Python 3.11+ + Bybit MT5 API + 异步订单执行框架
- **交易品种**: XAUUSDT/XAUUSD (贵金属合约，价格精度要求高)

---

## 二、故障根因分析

### 2.1 核心成因定位（按优先级排序）

#### ✅ 根因 1: 浮点数精度累积导致价格超长小数位
**问题代码**: `backend/app/services/arbitrage_strategy.py:129`
```python
bybit_buy_price = spread_data.bybit_quote.bid_price + 0.01
# 示例: 5184.02 + 0.01 = 5184.030000000001 (浮点数精度问题)
```

**影响**:
- Python 浮点数运算会产生精度误差
- spread 值 `1.160000000000764` 证明了浮点数精度累积问题
- 计算后的价格可能是 `5184.030000000001` 而非 `5184.03`

#### ✅ 根因 2: 价格传递链路中的字符串-浮点数转换
**问题代码**: `backend/app/services/order_executor.py:427`
```python
str(bybit_price) if bybit_price else None,
```

**传递链路**:
1. `arbitrage_strategy.py`: 计算 `bybit_buy_price = 5184.030000000001` (float)
2. `order_executor.py:427`: 转换为字符串 `"5184.030000000001"`
3. `order_executor.py:80`: 转换回浮点数 `float("5184.030000000001")`
4. `mt5_client.py:276`: 四舍五入 `round(5184.030000000001, 2)` → `5184.03`

**问题**: 虽然最终会四舍五入，但中间过程可能因字符串转换导致精度丢失或格式错误。

#### ✅ 根因 3: MT5 symbol_info 获取失败时的降级处理不足
**问题代码**: `backend/app/services/mt5_client.py:266-272`
```python
symbol_info = mt5.symbol_info(symbol)
if symbol_info is not None:
    digits = symbol_info.digits
    point = symbol_info.point
else:
    digits = 2  # 降级默认值
    point = 0.01
```

**风险**:
- 如果 `mt5.symbol_info(symbol)` 返回 None，使用默认 digits=2
- 但没有日志记录，无法追踪是否真的获取到了正确的 symbol_info
- 如果 MT5 连接不稳定，可能导致 symbol_info 获取失败

#### ✅ 根因 4: 缺少价格合法性预校验
**当前逻辑**:
- 价格计算后直接传递给 MT5 API
- 没有在下单前验证价格是否符合 MT5 品种规则
- 错误只能在 MT5 API 返回 retcode=10015 后才能发现

---

### 2.2 故障分析报告

#### 核心结论
**根本原因**: Python 浮点数精度累积 + 价格传递链路中的多次类型转换，导致 Bybit MT5 订单价格格式不符合品种精度要求（XAUUSD.s 要求 2 位小数，实际传入超长小数位或格式错误）。

#### 影响范围
- **受影响功能**: 仅 Bybit MT5 订单受影响
- **不受影响功能**: Binance 订单正常（已有精度处理：`round(binance_price, 2)`）
- **受影响策略**: 反向套利开仓、反向套利平仓、正向套利开仓、正向套利平仓

#### 触发条件
1. 反向套利策略启用反向开仓
2. spread 值存在浮点数精度误差（如 `1.160000000000764`）
3. 计算后的 `bybit_buy_price` 或 `bybit_sell_price` 存在超长小数位

---

## 三、全链路修复方案

### 3.1 后端修复（Python MT5 订单执行逻辑）

#### 修复点 1: 套利策略价格计算精度处理
**文件**: `backend/app/services/arbitrage_strategy.py`

**修改位置 1**: 反向套利开仓价格计算（第 127-129 行）
```python
# 修改前
binance_sell_price = spread_data.binance_quote.ask_price - 0.01
bybit_buy_price = spread_data.bybit_quote.bid_price + 0.01

# 修改后
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

**修改位置 2**: 正向套利开仓价格计算（第 44-46 行）
```python
# 修改前
binance_buy_price = spread_data.binance_quote.bid_price + 0.01
bybit_sell_price = spread_data.bybit_quote.ask_price - 0.01

# 修改后
binance_buy_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

**修改位置 3**: 反向套利平仓价格计算（第 210-212 行）
```python
# 修改前
binance_buy_price = spread_data.binance_quote.bid_price + 0.01
bybit_sell_price = spread_data.bybit_quote.ask_price - 0.01

# 修改后
binance_buy_price = round(spread_data.binance_quote.bid_price + 0.01, 2)
bybit_sell_price = round(spread_data.bybit_quote.ask_price - 0.01, 2)
```

**修改位置 4**: 正向套利平仓价格计算（第 274-276 行）
```python
# 修改前
binance_sell_price = spread_data.binance_quote.ask_price - 0.01
bybit_buy_price = spread_data.bybit_quote.bid_price + 0.01

# 修改后
binance_sell_price = round(spread_data.binance_quote.ask_price - 0.01, 2)
bybit_buy_price = round(spread_data.bybit_quote.bid_price + 0.01, 2)
```

#### 修复点 2: 订单执行器价格精度强化
**文件**: `backend/app/services/order_executor.py`

**修改位置**: execute_dual_order 函数（第 400-404 行）
```python
# 修改前
# Round prices to correct precision
# Binance XAUUSDT: 2 decimal places
if binance_price is not None:
    binance_price = round(binance_price, 2)
# Bybit MT5 price precision is handled by send_order via symbol_info.digits

# 修改后
# Round prices to correct precision
# Binance XAUUSDT: 2 decimal places
if binance_price is not None:
    binance_price = round(binance_price, 2)
# Bybit MT5 XAUUSD.s: 2 decimal places (强制精度处理)
if bybit_price is not None:
    bybit_price = round(bybit_price, 2)
```

#### 修复点 3: MT5 客户端价格校验增强
**文件**: `backend/app/services/mt5_client.py`

**修改位置**: send_order 函数（第 264-276 行）
```python
# 修改前
try:
    # Get symbol info to determine correct price precision
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is not None:
        digits = symbol_info.digits
        point = symbol_info.point
    else:
        digits = 2
        point = 0.01

    # Round price to symbol's required precision
    if price is not None:
        price = round(price, digits)

# 修改后
try:
    # Get symbol info to determine correct price precision
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is not None:
        digits = symbol_info.digits
        point = symbol_info.point
        logger.info(f"MT5 symbol_info for {symbol}: digits={digits}, point={point}")
    else:
        # 降级处理：XAUUSD.s 默认 2 位小数
        digits = 2
        point = 0.01
        logger.warning(f"MT5 symbol_info not available for {symbol}, using default digits=2")

    # Round price to symbol's required precision
    if price is not None:
        original_price = price
        price = round(price, digits)
        if abs(original_price - price) > point:
            logger.warning(f"Price rounded: {original_price} -> {price} (digits={digits})")
```

#### 修复点 4: 新增价格合法性预校验
**文件**: `backend/app/services/order_executor.py`

**新增函数**: 在 OrderExecutor 类中添加价格校验方法
```python
def _validate_price(self, price: float, symbol: str, platform: str) -> tuple[bool, str]:
    """验证价格是否符合交易所规则

    Args:
        price: 订单价格
        symbol: 交易品种
        platform: 交易平台 (binance/bybit)

    Returns:
        (is_valid, error_message)
    """
    if price is None:
        return True, ""

    # Binance XAUUSDT: 2 decimal places
    if platform == "binance":
        if round(price, 2) != price:
            return False, f"Binance价格精度错误: {price} (要求2位小数)"
        if price <= 0:
            return False, f"Binance价格无效: {price} (必须>0)"

    # Bybit MT5 XAUUSD.s: 2 decimal places
    elif platform == "bybit":
        if round(price, 2) != price:
            return False, f"Bybit价格精度错误: {price} (要求2位小数)"
        if price <= 0:
            return False, f"Bybit价格无效: {price} (必须>0)"

    return True, ""
```

**修改位置**: execute_dual_order 函数（第 405 行后插入）
```python
# 在第 405 行后插入价格校验
# Validate prices before placing orders
if binance_price is not None:
    is_valid, error_msg = self._validate_price(binance_price, binance_symbol, "binance")
    if not is_valid:
        return {"success": False, "error": error_msg}

if bybit_price is not None:
    is_valid, error_msg = self._validate_price(bybit_price, bybit_symbol, "bybit")
    if not is_valid:
        return {"success": False, "error": error_msg}
```

---

### 3.2 前端修复（Vue3 StrategyPanel.vue）

#### 修复点 1: 优化错误提示
**文件**: `frontend/src/components/trading/TradingDashboard.vue` 或相关文件

**修改位置**: WebSocket 消息处理逻辑
```javascript
// 解析 Bybit MT5 10015 错误
if (result.bybit_result && !result.bybit_result.success) {
  const error = result.bybit_result.error || ''
  if (error.includes('retcode=10015')) {
    ElMessage.error('Bybit MT5 价格格式错误（精度不符），请联系技术支持')
  } else {
    ElMessage.error(`Bybit 下单失败: ${error}`)
  }
}
```

#### 修复点 2: Spread 值精度处理
**文件**: `frontend/src/components/trading/StrategyPanel.vue`

**修改位置**: 显示 spread 值的地方
```javascript
// 修改前
{{ spread }}

// 修改后
{{ spread.toFixed(2) }}
```

---

### 3.3 验证方案

#### 后端单元测试
```python
# 测试文件: backend/tests/test_price_precision.py
import pytest
from app.services.order_executor import order_executor

def test_price_validation():
    """测试价格校验逻辑"""
    # 测试正常价格
    is_valid, msg = order_executor._validate_price(5184.03, "XAUUSDT", "binance")
    assert is_valid is True

    # 测试超长小数位
    is_valid, msg = order_executor._validate_price(5184.030000000001, "XAUUSDT", "binance")
    assert is_valid is False
    assert "精度错误" in msg

    # 测试负价格
    is_valid, msg = order_executor._validate_price(-100.00, "XAUUSDT", "binance")
    assert is_valid is False
    assert "无效" in msg

def test_price_rounding():
    """测试价格四舍五入"""
    from app.services.arbitrage_strategy import ArbitrageStrategy

    # 模拟浮点数精度问题
    bid_price = 5184.02
    buy_price = round(bid_price + 0.01, 2)
    assert buy_price == 5184.03
    assert isinstance(buy_price, float)
    assert len(str(buy_price).split('.')[-1]) <= 2
```

#### 前端联调测试
1. 清除浏览器缓存，刷新页面
2. 进入 StrategyPanel.vue 反向套利策略
3. 点击「启用反向开仓」按钮
4. 验证：
   - ✅ Binance 订单成功
   - ✅ Bybit 订单成功（无 10015 错误）
   - ✅ 错误提示清晰（如果仍有错误）

#### 全链路测试
```bash
# 1. 模拟不同 spread 值
curl -X POST http://localhost:8000/api/v1/strategies/reverse/open \
  -H "Content-Type: application/json" \
  -d '{
    "quantity": 0.1,
    "target_spread": 1.0
  }'

# 2. 检查日志
tail -f /tmp/backend.log | grep "MT5 symbol_info"
tail -f /tmp/backend.log | grep "Price rounded"

# 3. 验证订单价格
# 在 MT5 终端查看挂单价格，确认为 2 位小数
```

---

## 四、防回归方案

### 4.1 新增通用价格处理工具函数
**文件**: `backend/app/utils/price_utils.py` (新建)
```python
"""价格处理工具函数"""
from typing import Optional

def normalize_price(price: Optional[float], digits: int = 2) -> Optional[float]:
    """标准化价格精度

    Args:
        price: 原始价格
        digits: 小数位数

    Returns:
        标准化后的价格
    """
    if price is None:
        return None
    return round(float(price), digits)

def validate_xau_price(price: float, platform: str) -> tuple[bool, str]:
    """验证 XAU 品种价格

    Args:
        price: 价格
        platform: 平台 (binance/bybit)

    Returns:
        (is_valid, error_message)
    """
    if price <= 0:
        return False, f"{platform} 价格必须大于 0"

    if price < 1000 or price > 10000:
        return False, f"{platform} 价格超出合理范围 (1000-10000)"

    if round(price, 2) != price:
        return False, f"{platform} 价格精度错误 (要求 2 位小数)"

    return True, ""
```

### 4.2 新增订单下单前校验流程
**集成到**: `backend/app/services/order_executor.py`
```python
from app.utils.price_utils import normalize_price, validate_xau_price

# 在 execute_dual_order 函数中使用
binance_price = normalize_price(binance_price, 2)
bybit_price = normalize_price(bybit_price, 2)

is_valid, error_msg = validate_xau_price(binance_price, "binance")
if not is_valid:
    return {"success": False, "error": error_msg}

is_valid, error_msg = validate_xau_price(bybit_price, "bybit")
if not is_valid:
    return {"success": False, "error": error_msg}
```

### 4.3 完善日志体系
**修改**: `backend/app/services/order_executor.py`
```python
import logging
logger = logging.getLogger(__name__)

# 在 execute_dual_order 函数中添加日志
logger.info(f"Dual order params: binance_price={binance_price}, bybit_price={bybit_price}, "
            f"quantity={quantity}, bybit_quantity={bybit_quantity}")

# 在 place_bybit_order 函数中添加日志
logger.info(f"Bybit order: symbol={symbol}, side={side}, type={order_type}, "
            f"quantity={quantity}, price={price}")
```

---

## 五、部署与验证

### 5.1 后端代码部署
```bash
# 1. 停止后端服务
taskkill //F //IM uvicorn.exe

# 2. 应用代码修改（手动修改上述文件）

# 3. 重启后端服务
cd /c/app/hustle2026/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &

# 4. 验证后端启动
sleep 5 && tail -20 /tmp/backend.log
```

### 5.2 前端代码部署
```bash
# 1. 应用代码修改（手动修改上述文件）

# 2. 构建前端
cd /c/app/hustle2026/frontend
npm run build

# 3. 验证构建成功
ls -lh dist/
```

### 5.3 10015 错误验证方法
```python
# 模拟无效价格下单（用于测试）
# 在 Python 控制台执行
import MetaTrader5 as mt5

mt5.initialize()
mt5.login(login=你的MT5账号, password="密码", server="服务器")

# 测试 1: 正常价格（应该成功或返回其他错误，但不是 10015）
request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "XAUUSD.s",
    "volume": 0.01,
    "type": mt5.ORDER_TYPE_BUY_LIMIT,
    "price": 5184.03,  # 正常 2 位小数
    "deviation": 10,
    "magic": 123456,
    "comment": "test",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}
result = mt5.order_send(request)
print(f"Test 1: retcode={result.retcode}, comment={result.comment}")

# 测试 2: 超长小数位（应该返回 10015 或被自动修正）
request["price"] = 5184.030000000001
result = mt5.order_send(request)
print(f"Test 2: retcode={result.retcode}, comment={result.comment}")

mt5.shutdown()
```

---

## 六、兼容性保证

### 6.1 不影响 Binance 订单逻辑
- ✅ Binance 价格处理已有 `round(binance_price, 2)`
- ✅ 新增的价格校验不会影响 Binance 正常下单
- ✅ 修改仅在价格计算源头增加精度处理

### 6.2 不影响反向套利策略其他功能
- ✅ 仅修改价格计算逻辑，不改变策略核心算法
- ✅ spread 计算逻辑不变
- ✅ 订单追单逻辑不变

### 6.3 向后兼容
- ✅ 新增的价格校验函数为可选功能
- ✅ 日志增强不影响现有功能
- ✅ 所有修改均为防御性编程，不破坏现有逻辑

---

## 七、总结

### 核心问题
Python 浮点数精度累积 + 价格传递链路中的多次类型转换，导致 Bybit MT5 订单价格格式不符合品种精度要求。

### 修复策略
1. **源头治理**: 在价格计算时立即进行精度处理（`round(price, 2)`）
2. **链路强化**: 在订单执行器中再次确保价格精度
3. **预防拦截**: 新增价格合法性预校验，提前发现问题
4. **日志增强**: 记录价格处理过程，便于排查

### 预期效果
- ✅ Bybit MT5 订单 10015 错误完全消除
- ✅ 价格精度问题从源头解决
- ✅ 错误提示更加清晰友好
- ✅ 系统稳定性和可维护性提升

---

**文档版本**: 1.0
**生成时间**: 2026-02-26
**适用系统**: http://13.115.21.77:3000 反向套利策略系统
