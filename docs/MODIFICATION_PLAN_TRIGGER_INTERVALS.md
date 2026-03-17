# 触发频率独立配置修改方案

## 修改目标
将触发频率配置改为开仓和平仓各自独享，不再共享。同时确保保存配置时能够保存：
- 反开次数、反平次数、开仓触发频率、平仓触发频率（反向套利）
- 正开次数、正平次数、开仓触发频率、平仓触发频率（正向套利）

## 已完成的修改

### 1. 配置结构修改（第592-605行）✅
```javascript
const config = ref({
  openingMCoin: 5,
  closingMCoin: 5,
  openingEnabled: loadEnabledState(STORAGE_KEY_OPENING, false),
  closingEnabled: loadEnabledState(STORAGE_KEY_CLOSING, false),
  openingSyncQty: 3,  // 开仓次数
  closingSyncQty: 3,  // 平仓次数
  openingTriggerCheckInterval: 500, // 开仓触发器检测频率（毫秒）
  closingTriggerCheckInterval: 500, // 平仓触发器检测频率（毫秒）
  ladders: [...]
})
```

### 2. 保存配置逻辑修改（第1031-1053行）✅
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

### 3. 加载配置逻辑修改（第665-676行）✅
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

## 需要手动修改的部分

### 4. UI部分修改（第268-316行）⚠️ 需要手动修改

**当前代码（第268-316行）：**
```vue
        <!-- Data Sync Quantities -->
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label :for="`openingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正开次数' : '反开次数' }}
            </label>
            <input
              :id="`openingSyncQty-${type}`"
              v-model.number="config.openingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`closingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正平次数' : '反平次数' }}
            </label>
            <input
              :id="`closingSyncQty-${type}`"
              v-model.number="config.closingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`triggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
              触发频率
              <span class="text-[#0ecb81] ml-1">{{ config.triggerCheckInterval }}ms</span>
            </label>
            <input
              :id="`triggerCheckInterval-${type}`"
              v-model.number="config.triggerCheckInterval"
              type="number"
              step="100"
              min="500"
              max="1000"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
            <div class="text-xs text-gray-500 mt-0.5">
              建议值: 500ms
            </div>
          </div>
        </div>
```

**需要替换为：**
```vue
        <!-- Data Sync Quantities and Trigger Intervals -->
        <div class="space-y-2">
          <!-- Opening Configuration -->
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label :for="`openingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
                {{ type === 'forward' ? '正开次数' : '反开次数' }}
              </label>
              <input
                :id="`openingSyncQty-${type}`"
                v-model.number="config.openingSyncQty"
                type="number"
                step="1"
                min="1"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>

            <div>
              <label :for="`openingTriggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
                开仓触发频率
                <span class="text-[#0ecb81] ml-1">{{ config.openingTriggerCheckInterval }}ms</span>
              </label>
              <input
                :id="`openingTriggerCheckInterval-${type}`"
                v-model.number="config.openingTriggerCheckInterval"
                type="number"
                step="100"
                min="500"
                max="1000"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>
          </div>

          <!-- Closing Configuration -->
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label :for="`closingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
                {{ type === 'forward' ? '正平次数' : '反平次数' }}
              </label>
              <input
                :id="`closingSyncQty-${type}`"
                v-model.number="config.closingSyncQty"
                type="number"
                step="1"
                min="1"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>

            <div>
              <label :for="`closingTriggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
                平仓触发频率
                <span class="text-[#f6465d] ml-1">{{ config.closingTriggerCheckInterval }}ms</span>
              </label>
              <input
                :id="`closingTriggerCheckInterval-${type}`"
                v-model.number="config.closingTriggerCheckInterval"
                type="number"
                step="100"
                min="500"
                max="1000"
                class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
              />
            </div>
          </div>

          <div class="text-xs text-gray-500 text-center">
            建议值: 500ms
          </div>
        </div>
```

### 5. 执行时使用正确的触发频率（第1944行及其他地方）⚠️ 需要检查

在执行开仓/平仓时，需要使用对应的触发频率：
- 开仓操作：使用 `config.value.openingTriggerCheckInterval`
- 平仓操作：使用 `config.value.closingTriggerCheckInterval`

需要检查并修改所有使用 `trigger_check_interval` 的地方。

## 后端数据库修改

需要在后端添加两个新字段：
- `opening_trigger_check_interval` (Float)
- `closing_trigger_check_interval` (Float)

创建数据库迁移文件：
```python
# backend/alembic/versions/20260316_0002_split_trigger_intervals.py
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

def downgrade():
    op.drop_column('strategy_configs', 'closing_trigger_check_interval')
    op.drop_column('strategy_configs', 'opening_trigger_check_interval')
```

## 修改总结

### 已完成 ✅
1. 配置结构：分离为 `openingTriggerCheckInterval` 和 `closingTriggerCheckInterval`
2. 保存逻辑：保存两个独立的触发频率字段
3. 加载逻辑：加载两个独立的触发频率字段，并提供向后兼容

### 需要完成 ⚠️
1. UI部分：将触发频率输入框分为开仓和平仓两个独立的输入框
2. 执行逻辑：在执行时使用对应的触发频率
3. 后端数据库：添加新字段并迁移数据

## 测试验证

修改完成后，需要验证：
1. 保存配置后，开仓次数、平仓次数、开仓触发频率、平仓触发频率都能正确保存到数据库
2. 刷新页面后，配置能够正确加载
3. 执行开仓时使用开仓触发频率
4. 执行平仓时使用平仓触发频率
5. 反向套利和正向套利都能正常工作
