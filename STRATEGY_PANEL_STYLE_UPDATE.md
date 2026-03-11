# 策略面板样式调整

## 修改内容

### 1. 标题样式调整

**修改位置**: `frontend/src/components/trading/StrategyPanel.vue`

**修改内容**:
- 标题字体大小：从 `text-sm` 改为 `text-lg`（放大约 0.5 倍）
- 标题对齐：添加 `text-center` 居中显示
- 应用于：正向套利策略 和 反向套利策略

**修改前**:
```vue
<h3 :class="['text-sm font-bold', type === 'forward' ? 'text-[#FF2433]' : 'text-[#00C98B]']">
  {{ type === 'forward' ? '正向套利策略' : '反向套利策略' }}
</h3>
```

**修改后**:
```vue
<h3 :class="['text-lg font-bold text-center', type === 'forward' ? 'text-[#FF2433]' : 'text-[#00C98B]']">
  {{ type === 'forward' ? '正向套利策略' : '反向套利策略' }}
</h3>
```

### 2. 点差计算验证

**验证位置**: `frontend/src/components/trading/MarketCards.vue`

#### 反向套利策略点差计算

**公式**: `Binance 空单平均成本价 - Bybit 多单平均成本价`

**代码** (第 161-182 行):
```javascript
const reverseSpread = computed(() => {
  if (binanceShortPositions.value.length === 0 || bybitLongPositions.value.length === 0) {
    return 0
  }

  // Calculate Binance SHORT average cost price
  const binanceShortCost = binanceShortPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const binanceShortSize = binanceShortPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const binanceShortAvg = binanceShortSize > 0 ? binanceShortCost / binanceShortSize : 0

  // Calculate Bybit LONG average cost price
  const bybitLongCost = bybitLongPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const bybitLongSize = bybitLongPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const bybitLongAvg = bybitLongSize > 0 ? bybitLongCost / bybitLongSize : 0

  // Reverse spread = Binance SHORT cost - Bybit LONG cost
  return binanceShortAvg - bybitLongAvg
})
```

**验证结果**: ✅ **正确**

#### 正向套利策略点差计算

**公式**: `Bybit 空单平均成本价 - Binance 多单平均成本价`

**代码** (第 185-206 行):
```javascript
const forwardSpread = computed(() => {
  if (bybitShortPositions.value.length === 0 || binanceLongPositions.value.length === 0) {
    return 0
  }

  // Calculate Bybit SHORT average cost price
  const bybitShortCost = bybitShortPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const bybitShortSize = bybitShortPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const bybitShortAvg = bybitShortSize > 0 ? bybitShortCost / bybitShortSize : 0

  // Calculate Binance LONG average cost price
  const binanceLongCost = binanceLongPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const binanceLongSize = binanceLongPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const binanceLongAvg = binanceLongSize > 0 ? binanceLongCost / binanceLongSize : 0

  // Forward spread = Bybit SHORT cost - Binance LONG cost
  return bybitShortAvg - binanceLongAvg
})
```

**验证结果**: ✅ **正确**

## 点差计算说明

### 反向套利策略

**持仓组合**:
- Binance: 空单（SHORT）
- Bybit: 多单（LONG）

**点差计算**:
```
反向点差 = Binance 空单平均成本价 - Bybit 多单平均成本价
```

**示例**:
- Binance 空单平均成本价: 5200.00
- Bybit 多单平均成本价: 5197.00
- 反向点差 = 5200.00 - 5197.00 = 3.00

**意义**:
- 正值：Binance 空单成本高于 Bybit 多单成本，平仓会盈利
- 负值：Binance 空单成本低于 Bybit 多单成本，平仓会亏损

### 正向套利策略

**持仓组合**:
- Binance: 多单（LONG）
- Bybit: 空单（SHORT）

**点差计算**:
```
正向点差 = Bybit 空单平均成本价 - Binance 多单平均成本价
```

**示例**:
- Bybit 空单平均成本价: 5204.44
- Binance 多单平均成本价: 5200.00
- 正向点差 = 5204.44 - 5200.00 = 4.44

**意义**:
- 正值：Bybit 空单成本高于 Binance 多单成本，平仓会盈利
- 负值：Bybit 空单成本低于 Binance 多单成本，平仓会亏损

## 字体大小对照表

| Tailwind Class | 实际大小 | 说明 |
|---------------|---------|------|
| text-xs | 0.75rem (12px) | 超小 |
| text-sm | 0.875rem (14px) | 小 |
| text-base | 1rem (16px) | 基础 |
| text-lg | 1.125rem (18px) | 大 |
| text-xl | 1.25rem (20px) | 超大 |
| text-2xl | 1.5rem (24px) | 2倍大 |

**本次修改**:
- 标题：`text-sm` (14px) → `text-lg` (18px)，增加约 28.6%（约 0.5 倍）
- 实仓点差：保持 `text-2xl` (24px) 不变

## 视觉效果

### 修改前
```
反向套利策略          (14px, 左对齐, 绿色)
实仓: 0.07 点差: 0.00  (24px, 居中, 蓝色)
```

### 修改后
```
    反向套利策略        (18px, 居中, 绿色)
实仓: 0.07 点差: 0.00  (24px, 居中, 蓝色)
```

## 测试建议

1. **刷新浏览器**（Ctrl+F5）加载最新代码
2. **检查标题**：
   - 字体是否变大
   - 是否居中显示
   - 颜色是否正确（正向红色，反向绿色）
3. **检查点差**：
   - 反向策略：验证点差 = Binance 空单成本 - Bybit 多单成本
   - 正向策略：验证点差 = Bybit 空单成本 - Binance 多单成本

---

**修改时间**: 2026-03-10
**修改文件**: `frontend/src/components/trading/StrategyPanel.vue`
**验证文件**: `frontend/src/components/trading/MarketCards.vue`
