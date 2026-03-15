# 点差值提醒逻辑算法分析

## 1. 提醒模板配置

系统配置了4个点差提醒模板：

| 模板Key | 模板名称 | 触发条件 | 状态 |
|---------|---------|---------|------|
| forward_open_spread_alert | 优惠价格提醒 | 正向点差 >= 开仓阈值 | 激活 |
| forward_close_spread_alert | 价格回归提醒 | 正向点差 <= 平仓阈值 | 激活 |
| reverse_open_spread_alert | 反向优惠提醒 | 反向点差 >= 开仓阈值 | 激活 |
| reverse_close_spread_alert | 反向价格回归 | 反向点差 <= 平仓阈值 | 激活 |

## 2. 当前阈值配置

从risk_settings表读取：
- **正向开仓阈值** (forward_open_price): 3.0
- **正向平仓阈值** (forward_close_price): 0.2
- **反向开仓阈值** (reverse_open_price): 3.0
- **反向平仓阈值** (reverse_close_price): 0.2

## 3. 触发逻辑算法

### 3.1 检查频率
- 后台任务：AccountBalanceStreamer
- 检查间隔：每10秒
- 代码位置：`broadcast_tasks.py:318`

### 3.2 正向开仓提醒 (forward_open_spread_alert)

**触发条件：**
```python
if abs(market_data['forward_spread']) >= alert_settings['forwardOpenPrice']:
    # 触发提醒
```

**算法逻辑：**
1. 获取当前正向点差值 (forward_spread)
2. 取绝对值后与开仓阈值比较
3. 如果 |forward_spread| >= 3.0，触发提醒
4. 冷却时间：60秒（避免频繁通知）

**示例：**
- forward_spread = 3.5 → 触发 ✓
- forward_spread = -3.5 → 触发 ✓ (取绝对值)
- forward_spread = 2.8 → 不触发 ✗

### 3.3 正向平仓提醒 (forward_close_spread_alert)

**触发条件：**
```python
if abs(market_data['forward_spread']) <= alert_settings['forwardClosePrice']:
    # 触发提醒
```

**算法逻辑：**
1. 获取当前正向点差值
2. 取绝对值后与平仓阈值比较
3. 如果 |forward_spread| <= 0.2，触发提醒
4. 冷却时间：60秒

**示例：**
- forward_spread = 0.1 → 触发 ✓
- forward_spread = -0.15 → 触发 ✓
- forward_spread = 0.5 → 不触发 ✗

### 3.4 反向开仓提醒 (reverse_open_spread_alert)

**触发条件：**
```python
if abs(market_data['reverse_spread']) >= alert_settings['reverseOpenPrice']:
    # 触发提醒
```

**算法逻辑：**
1. 获取当前反向点差值 (reverse_spread)
2. 取绝对值后与开仓阈值比较
3. 如果 |reverse_spread| >= 3.0，触发提醒
4. 冷却时间：60秒

### 3.5 反向平仓提醒 (reverse_close_spread_alert)

**触发条件：**
```python
if abs(market_data['reverse_spread']) <= alert_settings['reverseClosePrice']:
    # 触发提醒
```

**算法逻辑：**
1. 获取当前反向点差值
2. 取绝对值后与平仓阈值比较
3. 如果 |reverse_spread| <= 0.2，触发提醒
4. 冷却时间：60秒

## 4. 冷却机制

**代码位置：** `spread_alert_service.py:111-132`

```python
def _should_send_alert(self, alert_type: str, user_id: str) -> bool:
    key = f"{alert_type}_{user_id}"
    now = get_beijing_time()

    if key in self.last_alert_time:
        last_time = self.last_alert_time[key]
        # 冷却时间60秒
        if (now - last_time).total_seconds() < 60:
            return False

    self.last_alert_time[key] = now
    return True
```

**冷却逻辑：**
- 每种提醒类型独立计时
- 同一用户同一类型提醒，60秒内只发送一次
- 不同类型提醒互不影响

## 5. 数据流程

```
1. AccountBalanceStreamer (每10秒)
   ↓
2. market_data_service.get_current_spread()
   ↓ 获取实时点差数据
3. SpreadAlertService.check_and_send_spread_alerts()
   ↓ 检查4种提醒条件
4. _should_send_alert()
   ↓ 检查冷却时间
5. _send_alert()
   ↓ 发送飞书通知 + WebSocket推送
6. NotificationLog
   ↓ 记录日志
```

## 6. 潜在问题分析

### 6.1 使用绝对值的影响

**当前逻辑：**
```python
if abs(market_data['forward_spread']) >= alert_settings['forwardOpenPrice']:
```

**问题：**
- 正向点差和反向点差都使用绝对值比较
- 无法区分点差的方向性（正值/负值）
- 可能导致误报

**示例场景：**
- 正向开仓应该在 forward_spread > 0 且较大时触发
- 但当前逻辑在 forward_spread < 0 且绝对值较大时也会触发
- 这可能不符合实际交易逻辑

### 6.2 开仓和平仓阈值的合理性

**当前配置：**
- 开仓阈值：3.0
- 平仓阈值：0.2

**问题：**
- 开仓和平仓阈值差距较大（3.0 vs 0.2）
- 中间区间（0.2 < spread < 3.0）没有提醒
- 可能错过一些重要的价格变化

### 6.3 冷却时间设置

**当前：60秒**

**考虑：**
- 市场波动快时，60秒可能太长
- 可能错过快速变化的机会
- 建议：根据市场波动性动态调整

## 7. 优化建议

### 7.1 区分点差方向

```python
# 正向开仓：应该检查正值且大于阈值
if market_data['forward_spread'] >= alert_settings['forwardOpenPrice']:
    # 触发提醒

# 正向平仓：应该检查接近0
if 0 <= market_data['forward_spread'] <= alert_settings['forwardClosePrice']:
    # 触发提醒
```

### 7.2 增加中间区间提醒

建议增加"价格变化"提醒：
- 当点差从开仓区间进入中间区间时
- 当点差从中间区间进入平仓区间时

### 7.3 动态冷却时间

```python
# 根据优先级调整冷却时间
cooldown_map = {
    'critical': 30,   # 关键提醒30秒
    'warning': 60,    # 警告提醒60秒
    'info': 120       # 信息提醒120秒
}
```

### 7.4 增加趋势判断

记录最近几次的点差值，判断趋势：
- 持续扩大 → 开仓机会增强
- 持续缩小 → 平仓时机临近
- 震荡波动 → 观望等待

## 8. 代码位置索引

| 功能 | 文件 | 行号 |
|------|------|------|
| 后台检查任务 | broadcast_tasks.py | 318-323 |
| 点差提醒服务 | spread_alert_service.py | 33-109 |
| 冷却机制 | spread_alert_service.py | 111-132 |
| 发送提醒 | spread_alert_service.py | 134-252 |
| WebSocket推送 | spread_alert_service.py | 254-303 |
| 阈值配置 | broadcast_tasks.py | 303-308 |
