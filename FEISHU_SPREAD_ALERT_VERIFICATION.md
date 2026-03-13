# 飞书点差消息推送验证报告

## 验证时间
2026-03-13

## 验证问题
检查飞书消息推送（点差行情）是否按照每个用户账户内不同的阈值配置发送个性化的点差消息。

## 验证结果

### ✅ 确认：系统已正确实现按用户个性化阈值发送点差消息

## 详细分析

### 1. 用户阈值配置存储

#### RiskSettings 模型 (risk_settings.py)
每个用户都有独立的风险设置记录，包含四个点差阈值：

```python
class RiskSettings(Base):
    # 反向套利阈值
    reverse_open_price = Column(Float, default=0.5)    # 反向开仓点差值
    reverse_close_price = Column(Float, default=0.2)   # 反向平仓点差值
    
    # 正向套利阈值
    forward_open_price = Column(Float, default=0.5)    # 正向开仓点差值
    forward_close_price = Column(Float, default=0.2)   # 正向平仓点差值
```

**特点**：
- 每个用户有独立的配置记录（user_id唯一索引）
- 四个独立的阈值字段
- 可以为每个用户设置不同的值

### 2. 阈值获取逻辑

#### broadcast_tasks.py (第156-185行)

```python
# 批量查询所有活跃用户的风险设置
result = await db.execute(
    select(RiskSettings).where(RiskSettings.user_id.in_(user_ids))
)
risk_settings_list = result.scalars().all()

# 为每个用户创建独立的阈值配置
for user_id, accounts in user_accounts.items():
    risk_settings = risk_settings_map.get(user_id)
    
    # 准备该用户的阈值设置
    alert_settings = {
        'forwardOpenPrice': risk_settings.forward_open_price,
        'forwardClosePrice': risk_settings.forward_close_price,
        'reverseOpenPrice': risk_settings.reverse_open_price,
        'reverseClosePrice': risk_settings.reverse_close_price,
    }
```

**特点**：
- 批量查询提高性能
- 为每个用户创建独立的alert_settings字典
- 每个用户使用自己的阈值配置

### 3. 点差检查逻辑

#### SpreadAlertService.check_and_send_spread_alerts (spread_alert_service.py)

系统对每个用户独立检查四种点差情况：

#### 3.1 正向开仓点差检查 (第52-63行)
```python
if market_data.get('forward_spread') and alert_settings.get('forwardOpenPrice'):
    if abs(market_data['forward_spread']) >= alert_settings['forwardOpenPrice']:
        # 发送正向开仓提醒
```

**触发条件**：当前正向点差 >= 用户配置的正向开仓阈值

#### 3.2 正向平仓点差检查 (第65-76行)
```python
if market_data.get('forward_spread') and alert_settings.get('forwardClosePrice'):
    if abs(market_data['forward_spread']) <= alert_settings['forwardClosePrice']:
        # 发送正向平仓提醒
```

**触发条件**：当前正向点差 <= 用户配置的正向平仓阈值

#### 3.3 反向开仓点差检查 (第78-89行)
```python
if market_data.get('reverse_spread') and alert_settings.get('reverseOpenPrice'):
    if abs(market_data['reverse_spread']) >= alert_settings['reverseOpenPrice']:
        # 发送反向开仓提醒
```

**触发条件**：当前反向点差 >= 用户配置的反向开仓阈值

#### 3.4 反向平仓点差检查 (第91-102行)
```python
if market_data.get('reverse_spread') and alert_settings.get('reverseClosePrice'):
    if abs(market_data['reverse_spread']) <= alert_settings['reverseClosePrice']:
        # 发送反向平仓提醒
```

**触发条件**：当前反向点差 <= 用户配置的反向平仓阈值

### 4. 消息发送逻辑

#### 模板匹配 (第165-180行)
```python
# 获取对应的飞书消息模板
result = await db.execute(
    select(NotificationTemplate).filter(
        and_(
            NotificationTemplate.template_key == template_key,
            NotificationTemplate.is_active == True,
            NotificationTemplate.enable_feishu == True,
            NotificationTemplate.auto_check_enabled == True
        )
    )
)
```

**四种模板**：
1. `forward_open_spread_alert` - 正向开仓点差提醒
2. `forward_close_spread_alert` - 正向平仓点差提醒
3. `reverse_open_spread_alert` - 反向开仓点差提醒
4. `reverse_close_spread_alert` - 反向平仓点差提醒

### 5. 冷却时间控制

#### 防止频繁推送 (第182-195行)
```python
cooldown = template.cooldown_seconds or 0
if cooldown > 0:
    key = f"{template_key}_{user_id}"
    # 检查该用户该类型消息的上次发送时间
    if key in self.last_alert_time:
        elapsed = (now - last_time).total_seconds()
        if elapsed < cooldown:
            return  # 在冷却期内，不发送
```

**特点**：
- 每个用户每种消息类型独立冷却
- 避免同一用户收到重复消息
- 不同用户之间互不影响

## 工作流程示例

### 场景：三个用户有不同的阈值配置

| 用户 | 正向开仓阈值 | 正向平仓阈值 | 反向开仓阈值 | 反向平仓阈值 |
|------|------------|------------|------------|------------|
| 用户A | 0.5 | 0.2 | 0.6 | 0.3 |
| 用户B | 0.3 | 0.1 | 0.4 | 0.15 |
| 用户C | 0.7 | 0.25 | 0.8 | 0.35 |

### 当前市场数据
- 正向点差：0.45
- 反向点差：0.55

### 推送结果

#### 用户A
- ❌ 正向开仓：0.45 < 0.5（不触发）
- ❌ 正向平仓：0.45 > 0.2（不触发）
- ❌ 反向开仓：0.55 < 0.6（不触发）
- ❌ 反向平仓：0.55 > 0.3（不触发）
- **结果：不发送任何消息**

#### 用户B
- ✅ 正向开仓：0.45 >= 0.3（触发）→ 发送正向开仓提醒
- ❌ 正向平仓：0.45 > 0.1（不触发）
- ✅ 反向开仓：0.55 >= 0.4（触发）→ 发送反向开仓提醒
- ❌ 反向平仓：0.55 > 0.15（不触发）
- **结果：发送2条消息（正向开仓 + 反向开仓）**

#### 用户C
- ❌ 正向开仓：0.45 < 0.7（不触发）
- ❌ 正向平仓：0.45 > 0.25（不触发）
- ❌ 反向开仓：0.55 < 0.8（不触发）
- ❌ 反向平仓：0.55 > 0.35（不触发）
- **结果：不发送任何消息**

## 验证结论

### ✅ 系统完全支持按用户个性化阈值发送点差消息

**验证要点**：

1. ✅ **独立配置**：每个用户在RiskSettings表中有独立的四个阈值字段
2. ✅ **独立查询**：系统为每个用户单独查询其风险设置
3. ✅ **独立判断**：使用每个用户自己的阈值进行点差比较
4. ✅ **独立发送**：根据每个用户的阈值触发情况决定是否发送消息
5. ✅ **独立冷却**：每个用户每种消息类型有独立的冷却时间控制

**关键代码路径**：
```
broadcast_tasks.py (_check_spread_alerts)
  ↓ 查询每个用户的RiskSettings
  ↓ 为每个用户创建独立的alert_settings
  ↓
SpreadAlertService.check_and_send_spread_alerts
  ↓ 使用用户的alert_settings进行四种点差检查
  ↓ 触发条件满足时发送对应的飞书消息
  ↓
_send_alert
  ↓ 获取消息模板
  ↓ 检查冷却时间（按用户+消息类型）
  ↓ 发送飞书消息
```

## 配置建议

### 用户如何设置个性化阈值

1. **前端界面**：在风险控制设置页面配置
2. **数据库字段**：
   - `forward_open_price` - 正向开仓点差阈值
   - `forward_close_price` - 正向平仓点差阈值
   - `reverse_open_price` - 反向开仓点差阈值
   - `reverse_close_price` - 反向平仓点差阈值

3. **推荐设置**：
   - 开仓阈值 > 平仓阈值（确保有利润空间）
   - 根据个人风险偏好调整
   - 激进型：较低的开仓阈值（如0.3）
   - 保守型：较高的开仓阈值（如0.7）

## 测试建议

1. **创建测试用户**：设置不同的阈值
2. **模拟市场数据**：设置不同的点差值
3. **验证消息推送**：确认每个用户收到正确的消息
4. **检查冷却时间**：验证不会频繁推送
5. **查看日志**：确认判断逻辑正确

## 总结

✅ **飞书点差消息推送系统已完全实现按用户个性化阈值发送功能**

每个用户可以独立配置四个点差阈值，系统会根据每个用户的配置独立判断是否发送消息，不同用户之间互不影响。
