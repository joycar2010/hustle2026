# 手动交易数量单位优化

## 修改概述

优化了 ManualTrading.vue 组件的数量输入逻辑，统一使用 XAU 作为输入单位，并自动处理 Binance 和 Bybit 的合约单位转换。

---

## 修改内容

### 1. 数量输入框改为整数

**修改前**:
```javascript
<input
  v-model.number="quantity"
  type="number"
  step="0.01"
  min="0.01"
  placeholder="0.01"
/>
const quantity = ref(0.01)
```

**修改后**:
```javascript
<input
  v-model.number="quantity"
  type="number"
  step="1"
  min="1"
  placeholder="1"
/>
const quantity = ref(1)
```

### 2. 添加单位说明和 Bybit 实际下单量显示

**修改后**:
```vue
<label class="text-xs text-gray-400 mb-1 block">下单总手数 (XAU)</label>
<input ... />
<div class="text-xs text-gray-500 mt-1">
  Bybit 实际下单量: {{ (quantity / 100).toFixed(2) }} Lot
</div>
```

**显示效果**:
- 输入 1 XAU → 显示 "Bybit 实际下单量: 0.01 Lot"
- 输入 100 XAU → 显示 "Bybit 实际下单量: 1.00 Lot"
- 输入 500 XAU → 显示 "Bybit 实际下单量: 5.00 Lot"

### 3. 自动转换下单数量

**修改后的 executeTrade 函数**:
```javascript
async function executeTrade(side) {
  if (loading.value) return
  loading.value = true
  try {
    // 根据平台转换数量
    // Binance: 1 XAU = 1 合约
    // Bybit: 1 Lot = 100 XAU，所以需要除以 100
    const actualQuantity = exchange.value === 'bybit' ? quantity.value / 100 : quantity.value

    await api.post('/api/v1/trading/manual/order', {
      exchange: exchange.value,
      side,
      quantity: actualQuantity,
    })
    showStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送`, true)
    await fetchRecentOrders()
  } catch (e) {
    showStatus(e.response?.data?.detail || '下单失败', false)
  } finally {
    loading.value = false
  }
}
```

---

## 合约单位转换逻辑

### Binance XAUUSDT 永续合约
- **合约单位**: 1 合约 = 1 XAU
- **转换公式**: 直接使用用户输入的 XAU 数量
- **示例**: 输入 100 XAU → 下单 100 合约

### Bybit XAUUSD.s (TradFi MT5)
- **合约单位**: 1 Lot = 100 XAU
- **转换公式**: XAU 数量 ÷ 100 = Lot 数量
- **示例**: 输入 100 XAU → 下单 1.00 Lot

### 转换比例
- **Binance : Bybit = 1 : 100**
- 用户输入统一为 XAU，系统自动转换为对应平台的实际下单量

---

## 功能影响范围

### 1. 买入开多 ✅
- 使用转换后的数量下单
- Binance: 直接使用 XAU
- Bybit: XAU ÷ 100 = Lot

### 2. 卖出开空 ✅
- 使用转换后的数量下单
- Binance: 直接使用 XAU
- Bybit: XAU ÷ 100 = Lot

### 3. 平仓所有持仓 ✅
- **不受影响**，该功能自动获取持仓数量，不依赖用户输入

### 4. 取消所有挂单 ✅
- **不受影响**，该功能自动获取挂单列表，不依赖用户输入

---

## 使用示例

### 示例 1: Binance 买入开多
1. 选择平台: Binance (XAUUSDT)
2. 输入数量: 100 XAU
3. 点击 "买入开多"
4. **实际下单**: 100 合约

### 示例 2: Bybit 卖出开空
1. 选择平台: Bybit MT5 (XAUUSD.s)
2. 输入数量: 500 XAU
3. 界面显示: "Bybit 实际下单量: 5.00 Lot"
4. 点击 "卖出开空"
5. **实际下单**: 5.00 Lot

### 示例 3: 最小下单量
- **Binance 最小**: 1 XAU (满足 ≥ 0.001 XAU 的要求)
- **Bybit 最小**: 1 XAU = 0.01 Lot (满足 ≥ 0.01 Lot 的要求)

---

## 技术细节

### 前端修改文件
- **文件**: `frontend/src/components/trading/ManualTrading.vue`
- **修改行数**:
  - 第 24-36 行: 数量输入框和单位显示
  - 第 126 行: 默认值改为 1
  - 第 183-199 行: executeTrade 函数添加数量转换逻辑

### 后端兼容性
- **无需修改后端代码**
- 后端 API 接收的 quantity 参数已经是转换后的实际下单量
- Binance API 接收 XAU 数量
- Bybit MT5 API 接收 Lot 数量

---

## 验证要点

### 1. 数量输入验证
- ✅ 只能输入整数
- ✅ 最小值为 1
- ✅ 默认值为 1

### 2. 单位显示验证
- ✅ 标签显示 "下单总手数 (XAU)"
- ✅ Bybit 实际下单量实时计算显示

### 3. 下单数量验证
- ✅ Binance 下单使用原始 XAU 数量
- ✅ Bybit 下单使用 XAU ÷ 100 的 Lot 数量

### 4. 最小下单量验证
- ✅ Binance: 1 XAU ≥ 0.001 XAU (满足)
- ✅ Bybit: 0.01 Lot ≥ 0.01 Lot (满足)

---

## 相关文档

- [手动交易功能详细说明](MANUAL_TRADING_FUNCTIONS_REPORT.md)
- [套利策略汇总报告](ARBITRAGE_STRATEGY_REPORT.md)

---

**修改时间**: 2026-02-26
**版本**: 1.0
**状态**: ✅ 已部署
