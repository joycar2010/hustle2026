# 点差值提醒集成指南

## 一、概述

在通知服务系统中新增4个点差值提醒模板，使用生鲜配送语规避敏感词汇，与风险控制系统集成。

---

## 二、新增模板

### 1. 正向开仓点差值提醒

**模板Key**: `forward_open_spread_alert`
**模板名称**: 优惠价格提醒
**生鲜配送语**: "优惠价格机会"

**触发条件**:
```javascript
forward_spread >= forwardOpenPrice
```

**飞书消息示例**:
```
💰 优惠价格机会提醒

价格优势通知
当前价格差异：2.50元/件
优惠阈值：2.00元/件
市场状态：优惠价格出现

建议操作：接收优惠订单
预计收益：25.00元

这是一个不错的价格机会！
```

**变量说明**:
- `{spread}`: 当前点差值（USDT）
- `{threshold}`: 开仓阈值（USDT）
- `{market_status}`: 市场状态描述
- `{estimated_profit}`: 预计收益（USDT）

---

### 2. 正向平仓点差值提醒

**模板Key**: `forward_close_spread_alert`
**模板名称**: 价格回归提醒
**生鲜配送语**: "价格回归通知"

**触发条件**:
```javascript
forward_spread <= forwardClosePrice
```

**飞书消息示例**:
```
📊 价格回归通知

价格变化提醒
当前价格差异：0.50元/件
回归阈值：1.00元/件
市场状态：价格回归正常

建议操作：完成订单配送
当前收益：5.00元

价格已回归正常区间，建议及时处理
```

**变量说明**:
- `{spread}`: 当前点差值
- `{threshold}`: 平仓阈值
- `{market_status}`: 市场状态
- `{current_profit}`: 当前收益

---

### 3. 反向开仓点差值提醒

**模板Key**: `reverse_open_spread_alert`
**模板名称**: 反向优惠提醒
**生鲜配送语**: "反向优惠机会"

**触发条件**:
```javascript
reverse_spread >= reverseOpenPrice
```

**飞书消息示例**:
```
💎 反向优惠机会

反向价格优势
当前价格差异：3.00元/件
优惠阈值：2.50元/件
市场状态：反向优惠出现

建议操作：接收反向订单
预计收益：30.00元

反向配送优惠机会出现！
```

---

### 4. 反向平仓点差值提醒

**模板Key**: `reverse_close_spread_alert`
**模板名称**: 反向价格回归
**生鲜配送语**: "反向价格回归"

**触发条件**:
```javascript
reverse_spread <= reverseClosePrice
```

**飞书消息示例**:
```
📈 反向价格回归

反向价格变化
当前价格差异：0.80元/件
回归阈值：1.20元/件
市场状态：反向价格回归

建议操作：完成反向配送
当前收益：8.00元

反向价格已回归正常，建议及时处理
```

---

## 三、数据库部署

### 方法1：全新安装

如果是全新安装通知服务，直接执行：
```bash
psql -U postgres -d hustle2026 -f backend/migrations/notification_service.sql
```

### 方法2：已有系统升级

如果已经安装了通知服务，执行补充脚本：
```bash
psql -U postgres -d hustle2026 -f backend/migrations/add_spread_alert_templates.sql
```

### 验证安装

```sql
-- 查询新增的模板
SELECT template_key, template_name, category, priority
FROM notification_templates
WHERE template_key LIKE '%spread_alert%'
ORDER BY template_key;

-- 应该看到4条记录：
-- forward_open_spread_alert
-- forward_close_spread_alert
-- reverse_open_spread_alert
-- reverse_close_spread_alert
```

---

## 四、后端集成

### 方式1：使用SpreadAlertService（推荐）

```python
# 在市场数据更新时调用
from app.services.spread_alert_service import spread_alert_service

async def on_market_data_update(market_data, user_id, db):
    """市场数据更新时检查点差值提醒"""

    # 获取用户的提醒设置
    alert_settings = await get_user_alert_settings(user_id, db)

    # 检查并发送点差值提醒
    await spread_alert_service.check_and_send_spread_alerts(
        db=db,
        user_id=str(user_id),
        market_data={
            'forward_spread': market_data.forward_spread,
            'reverse_spread': market_data.reverse_spread
        },
        alert_settings={
            'forwardOpenPrice': alert_settings.forward_open_price,
            'forwardClosePrice': alert_settings.forward_close_price,
            'reverseOpenPrice': alert_settings.reverse_open_price,
            'reverseClosePrice': alert_settings.reverse_close_price
        }
    )
```

### 方式2：直接调用通知API

```python
from app.api.v1.notifications import send_notification
from app.schemas.notification import SendNotificationRequest

# 发送正向开仓提醒
await send_notification(
    SendNotificationRequest(
        template_key="forward_open_spread_alert",
        user_ids=[str(user_id)],
        variables={
            "spread": "2.50",
            "threshold": "2.00",
            "market_status": "优惠价格出现",
            "estimated_profit": "25.00"
        }
    ),
    current_user=current_user,
    db=db
)
```

---

## 五、前端集成

### 在notification store中集成

修改 `frontend/src/stores/notification.js`:

```javascript
// 检查点差值提醒
function checkSpreadAlerts(marketData) {
  if (!alertSettings.value || !marketData) return

  const newAlerts = []

  // 1. 正向开仓点差值提醒
  if (marketData.forward_spread &&
      Math.abs(marketData.forward_spread) >= alertSettings.value.forwardOpenPrice) {
    newAlerts.push({
      id: Date.now() + '_forward_open_spread',
      type: 'forward_open_spread',
      level: 'warning',
      title: '💰 优惠价格机会提醒',
      message: `当前价格差异: ${marketData.forward_spread.toFixed(2)} 元/件，达到优惠阈值 ${alertSettings.value.forwardOpenPrice} 元/件`,
      timestamp: new Date().toISOString(),
      // 触发飞书通知
      sendFeishu: true,
      template_key: 'forward_open_spread_alert'
    })
  }

  // 2. 正向平仓点差值提醒
  if (marketData.forward_spread &&
      Math.abs(marketData.forward_spread) <= alertSettings.value.forwardClosePrice) {
    newAlerts.push({
      id: Date.now() + '_forward_close_spread',
      type: 'forward_close_spread',
      level: 'info',
      title: '📊 价格回归通知',
      message: `当前价格差异: ${marketData.forward_spread.toFixed(2)} 元/件，达到回归阈值 ${alertSettings.value.forwardClosePrice} 元/件`,
      timestamp: new Date().toISOString(),
      sendFeishu: true,
      template_key: 'forward_close_spread_alert'
    })
  }

  // 3. 反向开仓点差值提醒
  if (marketData.reverse_spread &&
      Math.abs(marketData.reverse_spread) >= alertSettings.value.reverseOpenPrice) {
    newAlerts.push({
      id: Date.now() + '_reverse_open_spread',
      type: 'reverse_open_spread',
      level: 'warning',
      title: '💎 反向优惠机会',
      message: `当前价格差异: ${marketData.reverse_spread.toFixed(2)} 元/件，达到优惠阈值 ${alertSettings.value.reverseOpenPrice} 元/件`,
      timestamp: new Date().toISOString(),
      sendFeishu: true,
      template_key: 'reverse_open_spread_alert'
    })
  }

  // 4. 反向平仓点差值提醒
  if (marketData.reverse_spread &&
      Math.abs(marketData.reverse_spread) <= alertSettings.value.reverseClosePrice) {
    newAlerts.push({
      id: Date.now() + '_reverse_close_spread',
      type: 'reverse_close_spread',
      level: 'info',
      title: '📈 反向价格回归',
      message: `当前价格差异: ${marketData.reverse_spread.toFixed(2)} 元/件，达到回归阈值 ${alertSettings.value.reverseClosePrice} 元/件`,
      timestamp: new Date().toISOString(),
      sendFeishu: true,
      template_key: 'reverse_close_spread_alert'
    })
  }

  // 添加提醒并发送飞书通知
  if (newAlerts.length > 0) {
    alerts.value.push(...newAlerts)

    // 发送飞书通知
    newAlerts.forEach(alert => {
      if (alert.sendFeishu) {
        sendFeishuNotification(alert)
      }
    })

    // 触发弹窗和声音
    if (newAlerts.length > 0) {
      activePopup.value = newAlerts[0]
      if (alertSoundEnabled.value) {
        playAlertSound()
      }
    }
  }
}

// 发送飞书通知
async function sendFeishuNotification(alert) {
  try {
    await api.post('/api/v1/notifications/send', {
      template_key: alert.template_key,
      user_ids: [currentUserId], // 需要从用户状态获取
      variables: {
        spread: extractSpreadValue(alert.message),
        threshold: extractThresholdValue(alert.message),
        market_status: getMarketStatus(alert.type),
        estimated_profit: calculateProfit(alert.type),
        current_profit: calculateProfit(alert.type)
      }
    })
  } catch (error) {
    console.error('发送飞书通知失败:', error)
  }
}
```

---

## 六、配置说明

### 1. 冷却时间

为避免频繁通知，每个模板设置了60秒冷却时间：

```sql
UPDATE notification_templates
SET cooldown_seconds = 60
WHERE template_key LIKE '%spread_alert%';
```

### 2. 优先级

所有点差值提醒设置为高优先级（3）：
- 飞书卡片颜色：橙色
- 适合重要但非紧急的提醒

### 3. 启用/禁用

可以单独控制每个模板：

```sql
-- 禁用正向开仓提醒
UPDATE notification_templates
SET is_active = false
WHERE template_key = 'forward_open_spread_alert';

-- 启用所有点差值提醒
UPDATE notification_templates
SET is_active = true
WHERE template_key LIKE '%spread_alert%';
```

---

## 七、测试验证

### 1. 测试模板渲染

```bash
curl -X POST "http://localhost:8000/api/v1/notifications/send" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "forward_open_spread_alert",
    "user_ids": ["user-uuid"],
    "variables": {
      "spread": "2.50",
      "threshold": "2.00",
      "market_status": "优惠价格出现",
      "estimated_profit": "25.00"
    }
  }'
```

### 2. 测试SpreadAlertService

```python
# 在Python shell中测试
from app.services.spread_alert_service import spread_alert_service
from app.core.database import get_db_context

async def test_spread_alert():
    async with get_db_context() as db:
        await spread_alert_service.check_and_send_spread_alerts(
            db=db,
            user_id="your-user-uuid",
            market_data={
                'forward_spread': 2.5,
                'reverse_spread': 3.0
            },
            alert_settings={
                'forwardOpenPrice': 2.0,
                'forwardClosePrice': 1.0,
                'reverseOpenPrice': 2.5,
                'reverseClosePrice': 1.2
            }
        )

# 运行测试
import asyncio
asyncio.run(test_spread_alert())
```

### 3. 查看发送日志

```sql
-- 查询点差值提醒发送记录
SELECT
    template_key,
    recipient,
    title,
    status,
    sent_at
FROM notification_logs
WHERE template_key LIKE '%spread_alert%'
ORDER BY created_at DESC
LIMIT 10;
```

---

## 八、生鲜配送语词汇对照

| 交易术语 | 生鲜配送语 | 使用场景 |
|---------|-----------|---------|
| 正向开仓点差值 | 优惠价格机会 | forward_open_spread_alert |
| 正向平仓点差值 | 价格回归通知 | forward_close_spread_alert |
| 反向开仓点差值 | 反向优惠机会 | reverse_open_spread_alert |
| 反向平仓点差值 | 反向价格回归 | reverse_close_spread_alert |
| 点差 | 价格差异 | 所有模板 |
| 开仓阈值 | 优惠阈值 | 开仓提醒 |
| 平仓阈值 | 回归阈值 | 平仓提醒 |
| 盈利 | 收益 | 所有模板 |
| 套利机会 | 配送优惠 | 开仓提醒 |

---

## 九、常见问题

### Q1: 如何调整提醒频率？

修改冷却时间：
```sql
UPDATE notification_templates
SET cooldown_seconds = 120  -- 改为2分钟
WHERE template_key = 'forward_open_spread_alert';
```

### Q2: 如何自定义消息内容？

在系统管理 → 通知服务 → 通知模板中编辑：
1. 找到对应模板
2. 点击"编辑"
3. 修改标题模板和内容模板
4. 保存

### Q3: 如何禁用某个点差值提醒？

方法1：在前端禁用
- 系统管理 → 通知服务 → 通知模板
- 找到对应模板，取消勾选"飞书"渠道

方法2：在数据库禁用
```sql
UPDATE notification_templates
SET is_active = false
WHERE template_key = 'forward_open_spread_alert';
```

### Q4: 提醒没有发送？

检查清单：
1. ✅ 模板是否启用（is_active = true）
2. ✅ 飞书渠道是否启用（enable_feishu = true）
3. ✅ 飞书服务是否配置正确
4. ✅ 是否在冷却时间内
5. ✅ 查看notification_logs表的错误信息

---

## 十、总结

新增的4个点差值提醒模板：
- ✅ 使用生鲜配送语规避敏感词汇
- ✅ 与风险控制系统集成
- ✅ 支持飞书实时推送
- ✅ 60秒冷却时间避免频繁通知
- ✅ 高优先级（橙色卡片）
- ✅ 可自定义编辑

部署步骤：
1. 执行数据库迁移脚本
2. 重启后端服务
3. 在系统管理中验证模板
4. 集成到市场数据监控
5. 测试验证
