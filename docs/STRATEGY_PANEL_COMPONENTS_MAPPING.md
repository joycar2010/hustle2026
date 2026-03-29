# StrategyPanel.vue 组件名称对照表

## 策略类型说明
- **type='forward'**: 正向套利策略面板
- **type='reverse'**: 反向套利策略面板

## 一、基础配置组件

| 配置项ID | 正向策略显示名称 | 反向策略显示名称 | 后端字段名 | 说明 |
|---------|----------------|----------------|-----------|------|
| `openingMCoin` | 正开单手数 | 反开单手数 | `openingMCoin` | 开仓时的单笔订单手数（XAU） |
| `closingMCoin` | 正平单手数 | 反平单手数 | `closingMCoin` | 平仓时的单笔订单手数（XAU） |
| `openingSyncQty` | 正开次数 | 反开次数 | `openingSyncQty` | 开仓触发次数要求 |
| `closingSyncQty` | 正平次数 | 反平次数 | `closingSyncQty` | 平仓触发次数要求 |
| `triggerCheckInterval` | 触发频率 | 触发频率 | `triggerCheckInterval` | 检查触发条件的时间间隔（ms） |

## 二、控制按钮组件

| 按钮类型 | 正向策略按钮文本 | 反向策略按钮文本 | 后端策略类型 | 说明 |
|---------|----------------|----------------|------------|------|
| 开仓控制按钮 | 正向开仓 | 反向开仓 | `forward_opening` / `reverse_opening` | 点击后开始/停止开仓策略 |
| 平仓控制按钮 | 正向平仓 | 反向平仓 | `forward_closing` / `reverse_closing` | 点击后开始/停止平仓策略 |

## 三、阶梯配置组件

| 配置项ID | 正向策略显示名称 | 反向策略显示名称 | 后端字段名 | 说明 |
|---------|----------------|----------------|-----------|------|
| `openPrice` | 正开差值 | 反开差值 | `opening_spread` | 开仓点差阈值 |
| `threshold` | 正平差值 | 反平差值 | `closing_spread` | 平仓点差阈值 |
| `qtyLimit` | 正下总手数 | 反下总手数 | `total_qty` | 该阶梯的总交易手数（XAU） |

## 四、显示信息组件

| 显示项 | 正向策略显示 | 反向策略显示 | 数据来源 | 说明 |
|-------|------------|------------|---------|------|
| 实仓 | forwardActualPosition | reverseActualPosition | MarketCards | 当前持仓数量 |
| 点差 | forwardSpread | reverseSpread | MarketCards | 当前点差值 |
| 点差显示标签 | 做多Binance点差 | 做多Bybit点差 | - | 点差类型说明 |
| 费用显示 | Binance 资金费 | Bybit 过夜费 | MarketCards | 交易费用 |

## 五、后端策略执行映射

### 正向套利策略（Forward）
| 前端操作 | 后端执行函数 | 交易所操作 | 说明 |
|---------|------------|-----------|------|
| 正向开仓 | `execute_forward_opening()` | Binance做多 + Bybit做空 | Binance ASK + Bybit ASK |
| 正向平仓 | `execute_forward_closing()` | Binance平多 + Bybit平空 | Binance BUY(ASK) + Bybit SELL(ASK) |

### 反向套利策略（Reverse）
| 前端操作 | 后端执行函数 | 交易所操作 | 说明 |
|---------|------------|-----------|------|
| 反向开仓 | `execute_reverse_opening()` | Binance做空 + Bybit做多 | Binance BID + Bybit BID |
| 反向平仓 | `execute_reverse_closing()` | Binance平空 + Bybit平多 | Binance SELL(BID) + Bybit BUY(BID) |

## 六、关键逻辑说明

### 1. 配置字段命名规则
- **前端显示**：根据策略类型（forward/reverse）动态显示"正"或"反"
- **后端字段**：统一使用英文字段名，不区分正反向
- **策略类型**：通过 `type` 参数区分，传递给后端时转换为对应的策略执行函数

### 2. 用户问题分析
用户描述："反向套利策略面板中正向平仓单手数设置5手后点击反向平仓功能按钮"

**正确理解**：
- 面板：反向套利策略面板（type='reverse'）
- 设置项：反平单手数（closingMCoin）= 5手
- 操作：点击"反向平仓"按钮
- 后端执行：`execute_reverse_closing()`

**可能的混淆点**：
- 用户说"正向平仓单手数"，实际应该是"反平单手数"
- 在反向策略面板中，所有配置都是针对反向策略的

### 3. 数据流向
```
前端StrategyPanel
  ↓ (用户配置)
config.closingMCoin = 5
  ↓ (点击按钮)
toggleClosingExecution()
  ↓ (API调用)
POST /api/v1/strategies/execute
  ↓ (后端处理)
execute_reverse_closing()
  ↓ (订单执行)
Binance SELL(BID) + Bybit BUY(BID)
```

## 七、常见问题对照

| 用户描述 | 实际含义 | 对应组件 |
|---------|---------|---------|
| "正向平仓单手数" | 在正向策略面板中的平仓单手数 | closingMCoin (forward) |
| "反向平仓单手数" | 在反向策略面板中的平仓单手数 | closingMCoin (reverse) |
| "正开差值" | 正向策略的开仓点差阈值 | openPrice (forward) |
| "反平差值" | 反向策略的平仓点差阈值 | threshold (reverse) |
| "正向开仓按钮" | 正向策略面板的开仓控制按钮 | 开仓控制 (forward) |
| "反向平仓按钮" | 反向策略面板的平仓控制按钮 | 平仓控制 (reverse) |

## 八、注意事项

1. **命名一致性**：前端显示名称会根据策略类型动态变化，但后端字段名保持统一
2. **策略独立性**：正向和反向策略是完全独立的，各自有独立的配置和状态
3. **按钮功能**：每个策略面板有两个按钮（开仓/平仓），分别控制该策略的开仓和平仓操作
4. **配置保存**：配置修改后需要点击"保存配置"或"保存策略"按钮才会生效
