# 套利策略持仓计算公式汇总

## 一、后端计算逻辑 (Backend)

### 1. PositionTracker 类 (单个阶梯持仓追踪器)

**位置:** `backend/app/services/position_manager.py`

**核心变量:**
- `current_position`: 当前持仓数量
- `total_opened`: 累计开仓总数
- `total_closed`: 累计平仓总数

**计算公式:**

#### 开仓操作 (add_opening):
```python
current_position += quantity
total_opened += quantity
```

#### 平仓操作 (add_closing):
```python
# 前提条件: quantity <= current_position
current_position -= quantity
total_closed += quantity
```

**关键约束:**
- 平仓数量不能超过当前持仓: `quantity <= current_position`
- 开仓数量不能超过最大持仓限制: `(current_position + quantity) <= max_position`

---

### 2. PositionManager 类 (全局持仓管理器)

**位置:** `backend/app/services/position_manager.py`

**功能:** 管理所有策略和阶梯的持仓追踪器

#### get_strategy_summary() 方法

**计算公式:**
```python
# 获取某个策略的所有阶梯持仓
positions = get_all_positions(strategy_id)

# 汇总计算
total_current_position = sum(p["current_position"] for p in positions)
total_opened = sum(p["total_opened"] for p in positions)
total_closed = sum(p["total_closed"] for p in positions)
```

**返回数据结构:**
```python
{
    "strategy_id": strategy_id,
    "total_current_position": total_current,  # 所有阶梯当前持仓之和
    "total_opened": total_opened,             # 所有阶梯累计开仓之和
    "total_closed": total_closed,             # 所有阶梯累计平仓之和
    "ladder_count": len(positions),           # 阶梯数量
    "ladders": positions                      # 各阶梯详细数据
}
```

---

## 二、前端计算逻辑 (Frontend)

### 1. StrategyPanel.vue (策略面板)

**位置:** `frontend/src/components/trading/StrategyPanel.vue`

**显示变量:**
- `positionSummary.total_current_position` - 当前持仓总数
- `positionSummary.total_opened` - 累计开仓总数
- `positionSummary.total_closed` - 累计平仓总数

**数据来源:**
```javascript
// API 调用
const response = await api.get(`/api/v1/strategies/positions/${configId}`)
positionSummary.value = response.data.summary
```

**数据结构:**
```javascript
{
  summary: {
    total_current_position: Number,  // 直接从后端获取
    total_opened: Number,            // 直接从后端获取
    total_closed: Number             // 直接从后端获取
  }
}
```

---

### 2. MarketCards.vue (市场卡片)

**位置:** `frontend/src/components/trading/MarketCards.vue`

**显示变量:**
- `forwardOpenPosition` - 正向开仓持仓数
- `forwardClosePosition` - 正向平仓持仓数
- `reverseOpenPosition` - 反向开仓持仓数
- `reverseClosePosition` - 反向平仓持仓数

#### 计算公式 (fetchStrategyPositions):

```javascript
// 1. 获取所有策略配置
const configs = await api.get('/api/v1/strategies/configs')

// 2. 初始化
forwardOpenPosition = 0
forwardClosePosition = 0
reverseOpenPosition = 0
reverseClosePosition = 0

// 3. 遍历每个策略配置
for (const config of configs) {
  // 获取该策略的持仓数据
  const data = await api.get(`/api/v1/strategies/positions/${config.config_id}`)

  // 判断策略类型
  const isForward = config.strategy_type === 'forward_arbitrage'
  const isReverse = config.strategy_type === 'reverse_arbitrage'

  // 过滤开仓和平仓阶梯
  const openingPositions = data.positions.filter(p => p.strategy_type === 'opening')
  const closingPositions = data.positions.filter(p => p.strategy_type === 'closing')

  // 计算该策略的开仓和平仓总数
  const totalOpening = openingPositions.reduce((sum, p) => sum + (p.current_position || 0), 0)
  const totalClosing = closingPositions.reduce((sum, p) => sum + (p.current_position || 0), 0)

  // 累加到对应的策略类型
  if (isForward) {
    forwardOpenPosition += totalOpening
    forwardClosePosition += totalClosing
  } else if (isReverse) {
    reverseOpenPosition += totalOpening
    reverseClosePosition += totalClosing
  }
}
```

#### WebSocket 实时更新 (updatePositionData):

```javascript
function updatePositionData(positions) {
  // 重置所有持仓数据
  forwardOpenPosition = 0
  forwardClosePosition = 0
  reverseOpenPosition = 0
  reverseClosePosition = 0

  // 遍历所有持仓记录
  positions.forEach(position => {
    // 判断策略类型
    const isForward = position.strategy_type?.includes('forward')
    const isReverse = position.strategy_type?.includes('reverse')

    // 判断动作类型
    const isOpening = position.action_type === 'opening'
    const isClosing = position.action_type === 'closing'

    // 获取当前持仓数量
    const currentPos = position.current_position || 0

    // 根据策略类型和动作类型累加
    if (isForward && isOpening) {
      forwardOpenPosition += currentPos
    } else if (isForward && isClosing) {
      forwardClosePosition += currentPos
    } else if (isReverse && isOpening) {
      reverseOpenPosition += currentPos
    } else if (isReverse && isClosing) {
      reverseClosePosition += currentPos
    }
  })
}
```

---

## 三、数据流向图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户执行开仓/平仓操作                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              PositionTracker.add_opening()                   │
│              PositionTracker.add_closing()                   │
│                                                              │
│  • current_position += quantity (开仓)                       │
│  • current_position -= quantity (平仓)                       │
│  • total_opened += quantity (开仓)                           │
│  • total_closed += quantity (平仓)                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│         PositionManager.get_strategy_summary()               │
│                                                              │
│  • total_current_position = Σ current_position (所有阶梯)   │
│  • total_opened = Σ total_opened (所有阶梯)                 │
│  • total_closed = Σ total_closed (所有阶梯)                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              API: /api/v1/strategies/positions/{id}          │
│                                                              │
│  返回: { summary: {...}, positions: [...] }                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    前端组件接收数据                          │
│                                                              │
│  • StrategyPanel: 显示 summary 数据                         │
│  • MarketCards: 根据 strategy_type 和 action_type 分类汇总  │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、关键字段说明

### Backend 字段:
- `strategy_id`: 策略配置ID
- `ladder_index`: 阶梯索引 (0-4)
- `strategy_type`: 策略类型 ('forward' 或 'reverse')
- `current_position`: 当前持仓数量
- `total_opened`: 累计开仓总数
- `total_closed`: 累计平仓总数

### Frontend 字段:
- `strategy_type`: 策略类型
  - `'forward_arbitrage'`: 正向套利
  - `'reverse_arbitrage'`: 反向套利
- `action_type`: 动作类型
  - `'opening'`: 开仓
  - `'closing'`: 平仓

---

## 五、计算示例

### 示例场景:
- 正向套利策略有3个阶梯
- 阶梯0: 开仓5手, 平仓2手, 当前持仓3手
- 阶梯1: 开仓3手, 平仓0手, 当前持仓3手
- 阶梯2: 开仓0手, 平仓0手, 当前持仓0手

### StrategyPanel 显示:
```
total_current_position = 3 + 3 + 0 = 6
total_opened = 5 + 3 + 0 = 8
total_closed = 2 + 0 + 0 = 2
```

### MarketCards 显示:
```
forwardOpenPosition = 6  (所有正向开仓阶梯的 current_position 之和)
forwardClosePosition = 0 (所有正向平仓阶梯的 current_position 之和)
```

**注意:** MarketCards 中的 `forwardOpenPosition` 和 `forwardClosePosition` 是按照 `action_type` 分类的，而不是按照开仓/平仓操作历史分类。

---

## 六、数据一致性保证

1. **后端内存管理**: PositionManager 使用全局单例，确保所有操作共享同一份持仓数据
2. **WebSocket 实时推送**: 后端通过 WebSocket 推送 account_balance 消息，包含最新的 positions 数据
3. **前端实时更新**: 前端监听 WebSocket 消息，实时更新持仓显示
4. **初始化加载**: 组件挂载时通过 API 获取初始持仓数据

---

## 七、注意事项

1. **策略类型判断差异**:
   - Backend: `'forward'` / `'reverse'`
   - Frontend API: `'forward_arbitrage'` / `'reverse_arbitrage'`
   - Frontend WebSocket: `strategy_type?.includes('forward')` / `strategy_type?.includes('reverse')`

2. **action_type 的含义**:
   - `'opening'`: 表示该阶梯用于开仓操作
   - `'closing'`: 表示该阶梯用于平仓操作
   - 这是阶梯的属性，不是操作历史

3. **current_position 的含义**:
   - 表示该阶梯当前的净持仓数量
   - 开仓增加，平仓减少
   - 不会为负数

4. **数据更新频率**:
   - WebSocket: 实时推送 (每10秒或有变化时)
   - API 轮询: 已移除，完全依赖 WebSocket
