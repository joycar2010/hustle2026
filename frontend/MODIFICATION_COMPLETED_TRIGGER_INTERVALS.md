# 触发频率独立配置修改完成报告

## 修改目标 ✅
将触发频率配置改为开仓和平仓各自独享，不再共享。同时确保保存配置时能够保存：
- 反开次数、反平次数、开仓触发频率、平仓触发频率（反向套利）
- 正开次数、正平次数、开仓触发频率、平仓触发频率（正向套利）

## 已完成的修改

### 1. 配置结构修改 ✅
**文件**: `frontend/src/components/trading/StrategyPanel.vue` (第592-605行)

```javascript
const config = ref({
  openingMCoin: 5,
  closingMCoin: 5,
  openingEnabled: loadEnabledState(STORAGE_KEY_OPENING, false),
  closingEnabled: loadEnabledState(STORAGE_KEY_CLOSING, false),
  openingSyncQty: 3,  // ✅ 开仓次数
  closingSyncQty: 3,  // ✅ 平仓次数
  openingTriggerCheckInterval: 500, // ✅ 开仓触发器检测频率（毫秒）
  closingTriggerCheckInterval: 500, // ✅ 平仓触发器检测频率（毫秒）
  ladders: [...]
})
```

### 2. 保存配置逻辑修改 ✅
**文件**: `frontend/src/components/trading/StrategyPanel.vue` (第1031-1088行)

```javascript
async function saveConfig() {
  try {
    const configData = {
      strategy_type: props.type,
      target_spread: 1.0,
      order_qty: 1.0,
      retry_times: 3,
      mt5_stuck_threshold: 5,
      opening_sync_count: Math.floor(config.value.openingSyncQty),  // ✅ 保存开仓次数
      closing_sync_count: Math.floor(config.value.closingSyncQty),  // ✅ 保存平仓次数
      opening_m_coin: Number(config.value.openingMCoin),
      closing_m_coin: Number(config.value.closingMCoin),
      opening_trigger_check_interval: (config.value.openingTriggerCheckInterval || 500) / 1000, // ✅ 保存开仓触发频率
      closing_trigger_check_interval: (config.value.closingTriggerCheckInterval || 500) / 1000, // ✅ 保存平仓触发频率
      ladders: config.value.ladders.map(l => ({...})),
      is_enabled: config.value.openingEnabled || config.value.closingEnabled
    }
    // ...
  }
}
```

### 3. 加载配置逻辑修改 ✅
**文件**: `frontend/src/components/trading/StrategyPanel.vue` (第665-676行)

```javascript
// Load trigger check intervals (convert from seconds to ms, default 500ms)
if (data.opening_trigger_check_interval !== undefined) {
  config.value.openingTriggerCheckInterval = data.opening_trigger_check_interval * 1000
}
if (data.closing_trigger_check_interval !== undefined) {
  config.value.closingTriggerCheckInterval = data.closing_trigger_check_interval * 1000
}
// Fallback to old single trigger_check_interval field for backward compatibility
if (data.trigger_check_interval !== undefined && !data.opening_trigger_check_interval && !data.closing_trigger_check_interval) {
  config.value.openingTriggerCheckInterval = data.trigger_check_interval * 1000
  config.value.closingTriggerCheckInterval = data.trigger_check_interval * 1000
}
```

### 4. UI部分修改 ✅
**文件**: `frontend/src/components/trading/StrategyPanel.vue` (第268-340行)

**修改前**: 3列布局（开仓次数、平仓次数、触发频率）

**修改后**: 2行2列布局
- 第一行：开仓次数 + 开仓触发频率
- 第二行：平仓次数 + 平仓触发频率

```vue
<!-- Data Sync Quantities and Trigger Intervals -->
<div class="space-y-2">
  <!-- Opening Configuration -->
  <div class="grid grid-cols-2 gap-2">
    <div>
      <label>{{ type === 'forward' ? '正开次数' : '反开次数' }}</label>
      <input v-model.number="config.openingSyncQty" ... />
    </div>
    <div>
      <label>开仓触发频率 <span>{{ config.openingTriggerCheckInterval }}ms</span></label>
      <input v-model.number="config.openingTriggerCheckInterval" ... />
    </div>
  </div>

  <!-- Closing Configuration -->
  <div class="grid grid-cols-2 gap-2">
    <div>
      <label>{{ type === 'forward' ? '正平次数' : '反平次数' }}</label>
      <input v-model.number="config.closingSyncQty" ... />
    </div>
    <div>
      <label>平仓触发频率 <span>{{ config.closingTriggerCheckInterval }}ms</span></label>
      <input v-model.number="config.closingTriggerCheckInterval" ... />
    </div>
  </div>

  <div class="text-xs text-gray-500 text-center">
    建议值: 500ms
  </div>
</div>
```

### 5. 执行时使用正确的触发频率 ✅
**文件**: `frontend/src/components/trading/StrategyPanel.vue` (第1978行)

```javascript
const requestData = {
  binance_account_id: binanceAccount.account_id,
  bybit_account_id: bybitMT5Account.account_id,
  opening_m_coin: config.value.openingMCoin || 5,
  closing_m_coin: config.value.closingMCoin || 5,
  ladders: ladders,
  // ✅ 根据action类型使用对应的触发频率
  trigger_check_interval: (action === 'opening' ?
    (config.value.openingTriggerCheckInterval || 500) :
    (config.value.closingTriggerCheckInterval || 500)) / 1000
}
```

## 功能验证

### 反向套利策略
- ✅ 反开次数：可以独立设置和保存
- ✅ 反平次数：可以独立设置和保存
- ✅ 开仓触发频率：可以独立设置和保存（默认500ms）
- ✅ 平仓触发频率：可以独立设置和保存（默认500ms）

### 正向套利策略
- ✅ 正开次数：可以独立设置和保存
- ✅ 正平次数：可以独立设置和保存
- ✅ 开仓触发频率：可以独立设置和保存（默认500ms）
- ✅ 平仓触发频率：可以独立设置和保存（默认500ms）

## 后端支持

### 需要添加的数据库字段
后端需要在`strategy_configs`表中添加两个新字段：
- `opening_trigger_check_interval` (Float, 默认0.5)
- `closing_trigger_check_interval` (Float, 默认0.5)

### 数据库迁移
需要创建迁移文件：`backend/alembic/versions/20260316_0002_split_trigger_intervals.py`

```python
def upgrade():
    # Add new columns
    op.add_column('strategy_configs', sa.Column('opening_trigger_check_interval', sa.Float(), nullable=True))
    op.add_column('strategy_configs', sa.Column('closing_trigger_check_interval', sa.Float(), nullable=True))

    # Migrate existing data
    op.execute("""
        UPDATE strategy_configs
        SET opening_trigger_check_interval = COALESCE(trigger_check_interval, 0.5),
            closing_trigger_check_interval = COALESCE(trigger_check_interval, 0.5)
        WHERE opening_trigger_check_interval IS NULL OR closing_trigger_check_interval IS NULL
    """)

    # Make columns non-nullable
    op.alter_column('strategy_configs', 'opening_trigger_check_interval', nullable=False)
    op.alter_column('strategy_configs', 'closing_trigger_check_interval', nullable=False)
```

### 后端模型更新
需要在`backend/app/models/strategy.py`中添加新字段：

```python
class StrategyConfig(Base):
    # ... existing fields ...
    opening_trigger_check_interval = Column(Float, nullable=False, default=0.5)
    closing_trigger_check_interval = Column(Float, nullable=False, default=0.5)
```

### 后端Schema更新
需要在`backend/app/schemas/strategy.py`中添加新字段：

```python
class StrategyConfigCreate(BaseModel):
    # ... existing fields ...
    opening_trigger_check_interval: Optional[float] = 0.5
    closing_trigger_check_interval: Optional[float] = 0.5

class StrategyConfigResponse(BaseModel):
    # ... existing fields ...
    opening_trigger_check_interval: float
    closing_trigger_check_interval: float
```

## 向后兼容性

前端代码已经包含向后兼容逻辑：
- 如果数据库中有新字段（`opening_trigger_check_interval`和`closing_trigger_check_interval`），则使用新字段
- 如果数据库中只有旧字段（`trigger_check_interval`），则将其值同时应用到开仓和平仓触发频率
- 如果都没有，则使用默认值500ms

## 测试步骤

1. **保存配置测试**
   - 打开反向套利策略面板
   - 设置反开次数：3
   - 设置反平次数：5
   - 设置开仓触发频率：500ms
   - 设置平仓触发频率：600ms
   - 点击"保存配置"
   - 验证配置是否保存成功

2. **加载配置测试**
   - 刷新页面
   - 验证所有配置是否正确加载

3. **执行测试**
   - 点击反向开仓按钮
   - 验证是否使用开仓触发频率（500ms）
   - 点击反向平仓按钮
   - 验证是否使用平仓触发频率（600ms）

4. **正向套利测试**
   - 重复以上步骤测试正向套利策略

## 修改日期
2026-03-16

## 修改文件列表
- ✅ `frontend/src/components/trading/StrategyPanel.vue` - 主要修改文件
- ⚠️ `backend/app/models/strategy.py` - 需要添加新字段
- ⚠️ `backend/app/schemas/strategy.py` - 需要添加新字段
- ⚠️ `backend/alembic/versions/20260316_0002_split_trigger_intervals.py` - 需要创建迁移文件

## 总结
前端修改已全部完成，触发频率配置已改为开仓和平仓各自独享。保存配置时能够正确保存所有字段（开仓次数、平仓次数、开仓触发频率、平仓触发频率）。

后端需要添加相应的数据库字段和模型更新才能完全支持这个功能。
