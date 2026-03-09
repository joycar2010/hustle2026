# 点差提醒触发算法验证报告

## 1. 用户配置验证

### 实际数据库配置

| 用户 | Forward Open | Forward Close | Reverse Open | Reverse Close |
|------|--------------|---------------|--------------|---------------|
| **admin** | 3.0 | **1.0** | **2.0** | **1.0** |
| cq987 | 3.0 | 0.2 | 3.0 | 0.2 |
| no456 | NULL | NULL | NULL | NULL |

### 验证结果

✅ **确认：每个用户的提醒阈值独立配置**
- risk_settings表有user_id字段
- 每个用户可以设置不同的阈值
- admin用户的实际配置：
  - Forward Close: 1.0 (不是0.2)
  - Reverse Open: 2.0 (不是3.0)
  - Reverse Close: 1.0 (不是0.2)

## 2. 触发算法验证

### 代码实现（spread_alert_service.py）

```python
# 正向开仓 (line 52-63)
if abs(market_data['forward_spread']) >= alert_settings['forwardOpenPrice']:
    # 触发提醒

# 正向平仓 (line 66-77)
if abs(market_data['forward_spread']) <= alert_settings['forwardClosePrice']:
    # 触发提醒

# 反向开仓 (line 80-91)
if abs(market_data['reverse_spread']) >= alert_settings['reverseOpenPrice']:
    # 触发提醒

# 反向平仓 (line 94-105)
if abs(market_data['reverse_spread']) <= alert_settings['reverseClosePrice']:
    # 触发提醒
```

### 实际触发条件（以admin用户为例）

1. **正向开仓提醒**：`|forward_spread| >= 3.0`
   - ✅ 使用用户配置的forward_open_price
   - ✅ admin用户阈值：3.0

2. **正向平仓提醒**：`|forward_spread| <= 1.0`
   - ✅ 使用用户配置的forward_close_price
   - ✅ admin用户阈值：1.0（不是0.2）

3. **反向开仓提醒**：`|reverse_spread| >= 2.0`
   - ✅ 使用用户配置的reverse_open_price
   - ✅ admin用户阈值：2.0（不是3.0）

4. **反向平仓提醒**：`|reverse_spread| <= 1.0`
   - ✅ 使用用户配置的reverse_close_price
   - ✅ admin用户阈值：1.0（不是0.2）

## 3. 检查机制验证

### 当前实现

**代码位置：** broadcast_tasks.py:26

```python
self.interval = 10  # Update interval in seconds (every 10s)
```

**配置文件：** config.py:81-83

```python
MARKET_DATA_UPDATE_INTERVAL: int = 1  # seconds
SPREAD_RECORD_INTERVAL: int = 1  # seconds
ACCOUNT_SYNC_INTERVAL: int = 5  # seconds
```

### 验证结果

❌ **检查间隔不一致**
- **实际代码**：AccountBalanceStreamer每10秒检查一次
- **用户期望**：每1秒检查一次
- **配置文件**：MARKET_DATA_UPDATE_INTERVAL = 1秒（但未被使用）

**问题：** broadcast_tasks.py中硬编码了10秒间隔，没有使用配置文件中的1秒设置

## 4. 冷却时间验证

### 当前实现

**代码位置：** spread_alert_service.py:127-128

```python
# 冷却时间60秒
if (now - last_time).total_seconds() < 60:
    return False
```

### 验证结果

❌ **冷却时间不符合期望**
- **实际代码**：60秒冷却时间
- **用户期望**：5秒冷却时间

## 5. 问题总结

### ✅ 正确的部分

1. 每个用户的阈值独立配置（从risk_settings表读取）
2. 触发算法使用用户配置的阈值
3. 4种提醒独立触发

### ❌ 需要修正的部分

1. **检查间隔**
   - 当前：10秒
   - 应该：1秒
   - 修改位置：broadcast_tasks.py:26

2. **冷却时间**
   - 当前：60秒
   - 应该：5秒
   - 修改位置：spread_alert_service.py:128

3. **配置文件未使用**
   - config.py中定义了MARKET_DATA_UPDATE_INTERVAL = 1
   - 但broadcast_tasks.py没有使用这个配置

## 6. 修正建议

### 6.1 修改检查间隔

**文件：** broadcast_tasks.py

```python
# 修改前
self.interval = 10  # Update interval in seconds (every 10s)

# 修改后
from app.core.config import settings
self.interval = settings.MARKET_DATA_UPDATE_INTERVAL  # 1 second
```

### 6.2 修改冷却时间

**文件：** spread_alert_service.py

```python
# 修改前
if (now - last_time).total_seconds() < 60:
    return False

# 修改后
if (now - last_time).total_seconds() < 5:
    return False
```

### 6.3 添加配置项

**文件：** config.py

```python
# 添加点差提醒冷却时间配置
SPREAD_ALERT_COOLDOWN: int = 5  # seconds
```

## 7. 代码位置索引

| 项目 | 文件 | 行号 | 当前值 | 期望值 |
|------|------|------|--------|--------|
| 检查间隔 | broadcast_tasks.py | 26 | 10秒 | 1秒 |
| 冷却时间 | spread_alert_service.py | 128 | 60秒 | 5秒 |
| 配置定义 | config.py | 81 | 1秒 | ✓ |
| 阈值读取 | broadcast_tasks.py | 303-308 | ✓ | ✓ |
