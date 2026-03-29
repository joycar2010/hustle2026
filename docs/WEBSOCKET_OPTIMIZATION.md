# WebSocket实时推送优化 - StrategyPanel数据刷新

## 问题描述
StrategyPanel中的实仓和点差数据刷新太慢，之前使用定时轮询API的方式获取数据，导致数据更新延迟。

## 解决方案
改用WebSocket实时推送方式，与行情和点差数据保持一致的更新逻辑。

## 修改内容

### 1. 前端 - Market Store ([market.js](frontend/src/stores/market.js))

**新增功能**：
- 添加 `accountBalanceData` 响应式变量，用于存储账户余额数据
- 在WebSocket消息处理中添加 `account_balance` 消息类型的处理
- 导出 `accountBalanceData` 供组件使用

**关键代码**：
```javascript
// 新增账户余额数据存储
const accountBalanceData = ref(null)

// WebSocket消息处理
else if (msg.type === 'account_balance' && msg.data) {
  accountBalanceData.value = msg.data
}
```

### 2. 前端 - MarketCards组件 ([MarketCards.vue](frontend/src/components/trading/MarketCards.vue))

**新增功能**：
- 添加 `updateAccountBalanceFromWebSocket()` 函数处理WebSocket推送的账户余额数据
- 使用 `watch` 监听 `marketStore.accountBalanceData` 的变化
- 移除定时轮询 `fetchAccountData()` 的逻辑（保留初始加载）

**关键代码**：
```javascript
// 监听账户余额WebSocket推送（替代定时轮询）
watch(() => marketStore.accountBalanceData, (data) => {
  if (data) {
    updateAccountBalanceFromWebSocket(data)
  }
})

// 处理WebSocket推送的账户余额数据
function updateAccountBalanceFromWebSocket(data) {
  // 更新总盈利
  if (data.summary) {
    totalProfit.value = data.summary.daily_pnl || 0
  }

  // 更新实仓数据
  if (bybitAccounts.length > 0) {
    reverseActualPosition.value = bybitAccounts[0].balance?.total_positions || 0
  }
  if (binanceAccounts.length > 0) {
    forwardActualPosition.value = binanceAccounts[0].balance?.total_positions || 0
  }

  // 更新费用数据和持仓详情
  // ...
}
```

### 3. 后端 - WebSocket推送（已存在）

后端已经实现了账户余额的WebSocket推送功能：
- [broadcast_tasks.py](backend/app/tasks/broadcast_tasks.py) 中的 `AccountBalanceStreamer`
- 每30秒推送一次账户余额数据
- 消息类型：`account_balance`

## 数据流程

```
后端 AccountBalanceStreamer (30秒间隔)
  ↓
WebSocket推送 (type: 'account_balance')
  ↓
Market Store 接收并存储到 accountBalanceData
  ↓
MarketCards 监听 accountBalanceData 变化
  ↓
调用 updateAccountBalanceFromWebSocket() 更新数据
  ↓
通过 defineExpose 暴露给 StrategyPanel
  ↓
StrategyPanel 实时显示实仓和点差数据
```

## 性能提升

**优化前**：
- 使用定时轮询API（间隔未知）
- 每次请求都需要HTTP往返
- 数据更新延迟较大

**优化后**：
- 使用WebSocket实时推送（30秒间隔）
- 无需额外HTTP请求
- 数据更新延迟降低到30秒以内
- 与行情数据保持一致的更新频率

## 影响范围

**受益组件**：
1. **StrategyPanel** - 实仓和点差数据实时更新
   - 反向套利策略面板：`reverseActualPosition` 和 `reverseSpread`
   - 正向套利策略面板：`forwardActualPosition` 和 `forwardSpread`

2. **MarketCards** - 总盈利和费用数据实时更新
   - 总盈利 (`totalProfit`)
   - Bybit过夜费 (`bybitLongSwapFee`, `bybitShortSwapFee`)
   - Binance资金费 (`binanceLongFundingRate`, `binanceShortFundingRate`)

## 测试建议

1. 打开控制面板，观察StrategyPanel中的实仓和点差数据
2. 在后台进行交易操作，观察数据是否在30秒内更新
3. 检查浏览器控制台，确认WebSocket连接正常
4. 验证数据更新频率与行情数据一致

## 注意事项

1. WebSocket连接断开时，会自动重连（10秒后）
2. 初始加载时仍会调用一次 `fetchAccountData()` 获取初始数据
3. 后端推送间隔为30秒，可根据需要调整
4. 清理了未使用的变量 `timeSinceLastUpdate` 和 `formatSpread`
