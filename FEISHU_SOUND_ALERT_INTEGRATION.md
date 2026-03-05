# 飞书通知与声音提醒集成方案

## 概述

将飞书机器人卡片提醒与系统现有的声音提醒功能进行适配，确保用户在收到飞书通知的同时，前端也能播放对应的声音提醒。

---

## 一、现有声音提醒系统

### 1.1 声音文件类型映射

系统已支持5种提醒类型的声音文件配置：

| 提醒类型 | 声音文件字段 | 重复次数字段 | 默认次数 |
|---------|------------|-------------|---------|
| 单腿交易提醒 | `singleLegAlertSound` | `singleLegAlertRepeatCount` | 3 |
| 点差提醒 | `spreadAlertSound` | `spreadAlertRepeatCount` | 3 |
| 净资产提醒 | `netAssetAlertSound` | `netAssetAlertRepeatCount` | 3 |
| MT5卡顿提醒 | `mt5AlertSound` | `mt5AlertRepeatCount` | 3 |
| 爆仓价提醒 | `liquidationAlertSound` | `liquidationAlertRepeatCount` | 3 |

### 1.2 声音文件存储位置

- **上传文件**：`/uploads/sounds/` 目录
- **默认文件**：`/sounds/hello-moto.mp3`
- **访问URL**：`${VITE_API_BASE_URL}/uploads/sounds/filename.mp3`

### 1.3 声音播放逻辑

位置：`frontend/src/stores/notification.js` 第206-291行

```javascript
async function playAlertSound(alert) {
  // 根据 alert.type 判断使用哪个声音文件
  if (alert.type.includes('single_leg')) {
    soundFile = alertSettings.value.singleLegAlertSound
    repeatCount = alertSettings.value.singleLegAlertRepeatCount || 3
  } else if (alert.type.includes('forward') || alert.type.includes('reverse')) {
    soundFile = alertSettings.value.spreadAlertSound
    repeatCount = alertSettings.value.spreadAlertRepeatCount || 3
  } else if (alert.type.includes('asset')) {
    soundFile = alertSettings.value.netAssetAlertSound
    repeatCount = alertSettings.value.netAssetAlertRepeatCount || 3
  } else if (alert.type.includes('mt5')) {
    soundFile = alertSettings.value.mt5AlertSound
    repeatCount = alertSettings.value.mt5AlertRepeatCount || 3
  } else if (alert.type.includes('liquidation')) {
    soundFile = alertSettings.value.liquidationAlertSound
    repeatCount = alertSettings.value.liquidationAlertRepeatCount || 3
  }
}
```

---

## 二、新增通知模板与声音映射

### 2.1 模板与声音类型对应关系

| 模板Key | 模板名称 | 对应声音类型 | 声音文件字段 |
|---------|---------|------------|-------------|
| **点差值提醒（4个）** | | | |
| `forward_open_spread_alert` | 优惠价格提醒 | 点差提醒 | `spreadAlertSound` |
| `forward_close_spread_alert` | 价格回归提醒 | 点差提醒 | `spreadAlertSound` |
| `reverse_open_spread_alert` | 反向优惠提醒 | 点差提醒 | `spreadAlertSound` |
| `reverse_close_spread_alert` | 反向价格回归 | 点差提醒 | `spreadAlertSound` |
| **系统状态提醒（1个）** | | | |
| `mt5_lag_alert` | 配送系统延迟 | MT5提醒 | `mt5AlertSound` |
| **净资产提醒（2个）** | | | |
| `binance_net_asset_alert` | A仓库资产提醒 | 净资产提醒 | `netAssetAlertSound` |
| `bybit_net_asset_alert` | B仓库资产提醒 | 净资产提醒 | `netAssetAlertSound` |
| **爆仓价提醒（2个）** | | | |
| `binance_liquidation_alert` | A仓库安全线提醒 | 爆仓价提醒 | `liquidationAlertSound` |
| `bybit_liquidation_alert` | B仓库安全线提醒 | 爆仓价提醒 | `liquidationAlertSound` |
| **单腿提醒（1个）** | | | |
| `single_leg_alert` | 单边配送提醒 | 单腿提醒 | `singleLegAlertSound` |

### 2.2 Alert Type 命名规范

为了让前端能够正确识别并播放对应的声音，需要统一 alert type 命名：

```javascript
// 模板Key → Alert Type 映射
const TEMPLATE_TO_ALERT_TYPE = {
  // 点差值提醒
  'forward_open_spread_alert': 'forward_open',
  'forward_close_spread_alert': 'forward_close',
  'reverse_open_spread_alert': 'reverse_open',
  'reverse_close_spread_alert': 'reverse_close',

  // MT5提醒
  'mt5_lag_alert': 'mt5_lag',

  // 净资产提醒
  'binance_net_asset_alert': 'binance_asset',
  'bybit_net_asset_alert': 'bybit_asset',

  // 爆仓价提醒
  'binance_liquidation_alert': 'binance_liquidation',
  'bybit_liquidation_alert': 'bybit_liquidation',

  // 单腿提醒
  'single_leg_alert': 'single_leg_alert'
}
```

---

## 三、实施方案

### 3.1 后端：WebSocket推送通知

当飞书通知发送成功后，通过WebSocket向前端推送提醒消息。

**文件**：`backend/app/services/risk_alert_service.py`

**修改**：在发送飞书通知成功后，广播WebSocket消息

```python
from app.websocket.connection_manager import manager

async def _send_alert(
    self,
    user_id: str,
    template_key: str,
    variables: Dict[str, any],
) -> bool:
    """发送提醒通知"""
    try:
        # ... 现有的飞书发送逻辑 ...

        if success:
            # 更新冷却时间
            cache_key = f"{user_id}_{template_key}"
            self.cooldown_cache[cache_key] = datetime.utcnow()
            logger.info(f"Alert sent: {template_key} to user {user_id}")

            # 【新增】通过WebSocket推送到前端
            await self._broadcast_alert_to_frontend(
                user_id=user_id,
                template_key=template_key,
                template=template,
                variables=variables
            )

        return success

    except Exception as e:
        logger.error(f"Error sending alert {template_key}: {e}")
        return False

async def _broadcast_alert_to_frontend(
    self,
    user_id: str,
    template_key: str,
    template: NotificationTemplate,
    variables: Dict[str, any]
):
    """通过WebSocket广播提醒到前端"""
    try:
        # 映射模板Key到前端Alert Type
        alert_type_map = {
            'forward_open_spread_alert': 'forward_open',
            'forward_close_spread_alert': 'forward_close',
            'reverse_open_spread_alert': 'reverse_open',
            'reverse_close_spread_alert': 'reverse_close',
            'mt5_lag_alert': 'mt5_lag',
            'binance_net_asset_alert': 'binance_asset',
            'bybit_net_asset_alert': 'bybit_asset',
            'binance_liquidation_alert': 'binance_liquidation',
            'bybit_liquidation_alert': 'bybit_liquidation',
            'single_leg_alert': 'single_leg_alert'
        }

        alert_type = alert_type_map.get(template_key, template_key)

        # 映射优先级到前端level
        level_map = {
            1: 'info',
            2: 'info',
            3: 'warning',
            4: 'critical'
        }

        # 构造前端提醒消息
        alert_message = {
            "type": "risk_alert",
            "data": {
                "alert_type": alert_type,
                "level": level_map.get(template.priority, 'warning'),
                "title": template.title_template.format(**variables),
                "message": template.content_template.format(**variables),
                "timestamp": datetime.utcnow().isoformat(),
                "template_key": template_key
            }
        }

        # 广播到指定用户
        await manager.send_personal_message(
            message=alert_message,
            user_id=user_id
        )

        logger.info(f"Alert broadcasted to frontend: {template_key} for user {user_id}")

    except Exception as e:
        logger.error(f"Error broadcasting alert to frontend: {e}")
```

### 3.2 前端：监听WebSocket消息

**文件**：`frontend/src/stores/market.js`

**修改**：在WebSocket消息处理中添加 `risk_alert` 类型处理

```javascript
import { useNotificationStore } from './notification'

ws.onmessage = (event) => {
  try {
    const msg = JSON.parse(event.data)
    lastMessage.value = msg

    // Handle different message types
    if (msg.type === 'market_data' && msg.data) {
      // ... 现有的market_data处理 ...
    }

    // 【新增】处理风险提醒消息
    else if (msg.type === 'risk_alert' && msg.data) {
      const notificationStore = useNotificationStore()

      // 构造提醒对象
      const alert = {
        id: Date.now() + '_' + msg.data.alert_type,
        type: msg.data.alert_type,
        level: msg.data.level,
        title: msg.data.title,
        message: msg.data.message,
        timestamp: msg.data.timestamp
      }

      // 添加到提醒列表并触发弹窗和声音
      notificationStore.alerts.push(alert)
      notificationStore.triggerPopup(alert)
    }

  } catch (e) {
    console.error('WS parse error:', e)
  }
}
```

### 3.3 前端：确保声音播放逻辑完整

**文件**：`frontend/src/stores/notification.js`

**验证**：确保 `playAlertSound` 函数能够处理所有新增的 alert type

```javascript
async function playAlertSound(alert) {
  if (!alertSoundEnabled.value) return
  if (isAudioPlaying.value) return
  if (!alertSettings.value) return

  isAudioPlaying.value = true

  try {
    let soundFile = null
    let repeatCount = 3

    // 映射alert type到声音文件
    if (alert.type.includes('single_leg')) {
      soundFile = alertSettings.value.singleLegAlertSound
      repeatCount = alertSettings.value.singleLegAlertRepeatCount || 3
    }
    else if (alert.type.includes('forward') || alert.type.includes('reverse')) {
      // 包含：forward_open, forward_close, reverse_open, reverse_close
      soundFile = alertSettings.value.spreadAlertSound
      repeatCount = alertSettings.value.spreadAlertRepeatCount || 3
    }
    else if (alert.type.includes('asset')) {
      // 包含：binance_asset, bybit_asset, total_asset
      soundFile = alertSettings.value.netAssetAlertSound
      repeatCount = alertSettings.value.netAssetAlertRepeatCount || 3
    }
    else if (alert.type.includes('mt5')) {
      // 包含：mt5_lag
      soundFile = alertSettings.value.mt5AlertSound
      repeatCount = alertSettings.value.mt5AlertRepeatCount || 3
    }
    else if (alert.type.includes('liquidation')) {
      // 包含：binance_liquidation, bybit_liquidation
      soundFile = alertSettings.value.liquidationAlertSound
      repeatCount = alertSettings.value.liquidationAlertRepeatCount || 3
    }

    // 如果没有自定义声音，使用默认
    if (!soundFile) {
      soundFile = '/sounds/hello-moto.mp3'
    }

    // 播放声音...
    // ... 现有的播放逻辑 ...

  } catch (error) {
    console.error('Failed to play alert sound:', error)
  } finally {
    isAudioPlaying.value = false
  }
}
```

---

## 四、完整的消息流程

### 4.1 飞书通知 + 声音提醒流程

```
1. 触发条件满足（如点差达到阈值）
   ↓
2. 后端 RiskAlertService 检测到触发条件
   ↓
3. 发送飞书卡片消息到用户手机
   ↓
4. 飞书发送成功后，通过WebSocket广播到前端
   ↓
5. 前端 market.js 接收到 risk_alert 消息
   ↓
6. 调用 notificationStore.triggerPopup(alert)
   ↓
7. triggerPopup 调用 playAlertSound(alert)
   ↓
8. 根据 alert.type 选择对应的声音文件
   ↓
9. 播放声音（重复指定次数）
   ↓
10. 前端显示弹窗提醒
```

### 4.2 消息格式示例

**WebSocket消息格式**：

```json
{
  "type": "risk_alert",
  "data": {
    "alert_type": "forward_open",
    "level": "warning",
    "title": "💰 优惠价格机会提醒",
    "message": "**价格优势通知**\n当前价格差异：2.50元/件\n优惠阈值：2.00元/件\n\n建议操作：接收优惠订单\n预计收益：25.00元\n\n这是一个不错的价格机会！",
    "timestamp": "2026-03-05T10:30:15.123Z",
    "template_key": "forward_open_spread_alert"
  }
}
```

---

## 五、配置管理

### 5.1 系统管理界面配置

用户可以在 `http://13.115.21.77:3000/system` → "提醒设置" 中配置：

1. **上传声音文件**：
   - 单腿交易提醒声音
   - 点差提醒声音
   - 净资产提醒声音
   - MT5卡顿提醒声音
   - 爆仓价提醒声音

2. **设置重复次数**：
   - 每种提醒类型可设置播放1-10次

3. **启用/禁用声音**：
   - 全局声音开关（localStorage: `alertSoundEnabled`）
   - 单腿提醒开关（localStorage: `singleLegAlertEnabled`）

### 5.2 数据库存储

声音文件配置存储在 `risk_alert_settings` 表中：

```sql
-- 查询当前声音配置
SELECT
    single_leg_alert_sound,
    single_leg_alert_repeat_count,
    spread_alert_sound,
    spread_alert_repeat_count,
    net_asset_alert_sound,
    net_asset_alert_repeat_count,
    mt5_alert_sound,
    mt5_alert_repeat_count,
    liquidation_alert_sound,
    liquidation_alert_repeat_count
FROM risk_alert_settings
WHERE user_id = 'user-uuid';
```

---

## 六、测试验证

### 6.1 测试步骤

1. **上传声音文件**：
   ```bash
   # 在系统管理页面上传5种类型的MP3文件
   # 或使用默认的 hello-moto.mp3
   ```

2. **触发测试提醒**：
   ```bash
   # 使用API发送测试通知
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

3. **验证结果**：
   - ✅ 飞书收到卡片消息
   - ✅ 前端显示弹窗提醒
   - ✅ 播放对应的声音文件
   - ✅ 声音重复指定次数

### 6.2 调试方法

**查看WebSocket消息**：
```javascript
// 在浏览器Console中
import { useMarketStore } from '@/stores/market'
const marketStore = useMarketStore()

// 监听所有WebSocket消息
watch(() => marketStore.lastMessage, (msg) => {
  console.log('WebSocket message:', msg)
})
```

**查看声音播放日志**：
```javascript
// notification.js 中已有日志
console.log('Playing alert sound:', soundUrl)
```

---

## 七、部署清单

### 7.1 后端修改

- [ ] 修改 `backend/app/services/risk_alert_service.py`
  - [ ] 添加 `_broadcast_alert_to_frontend` 方法
  - [ ] 在 `_send_alert` 中调用WebSocket广播

- [ ] 修改 `backend/app/services/spread_alert_service.py`
  - [ ] 同样添加WebSocket广播功能

### 7.2 前端修改

- [ ] 修改 `frontend/src/stores/market.js`
  - [ ] 添加 `risk_alert` 消息类型处理

- [ ] 验证 `frontend/src/stores/notification.js`
  - [ ] 确认 `playAlertSound` 能处理所有新增的 alert type

### 7.3 测试验证

- [ ] 测试点差提醒（4个模板）
- [ ] 测试MT5卡顿提醒
- [ ] 测试净资产提醒（2个模板）
- [ ] 测试爆仓价提醒（2个模板）
- [ ] 测试单腿提醒
- [ ] 验证声音文件播放
- [ ] 验证重复次数设置
- [ ] 验证飞书通知发送

---

## 八、优化建议

### 8.1 声音文件管理

1. **预置声音库**：
   - 提供5-10个预置声音文件供用户选择
   - 存放在 `/public/sounds/` 目录

2. **声音文件格式**：
   - 推荐使用MP3格式（兼容性好）
   - 文件大小建议 < 500KB
   - 时长建议 2-5秒

3. **声音文件命名**：
   - `alert-spread.mp3` - 点差提醒
   - `alert-asset.mp3` - 净资产提醒
   - `alert-mt5.mp3` - MT5提醒
   - `alert-liquidation.mp3` - 爆仓价提醒
   - `alert-single-leg.mp3` - 单腿提醒

### 8.2 用户体验优化

1. **声音预览**：
   - 上传前可以试听
   - 保存后可以测试播放

2. **音量控制**：
   - 添加音量滑块（0-100%）
   - 存储在 localStorage

3. **静音时段**：
   - 设置免打扰时间段
   - 例如：22:00-08:00 不播放声音

4. **提醒历史**：
   - 记录最近50条提醒
   - 可查看、重播、删除

---

## 九、相关文档

- [风险控制提醒功能总结](RISK_ALERT_SUMMARY.md)
- [通知服务实施方案](NOTIFICATION_SERVICE_IMPLEMENTATION.md)
- [点差值提醒集成指南](SPREAD_ALERT_INTEGRATION_GUIDE.md)

---

## 总结

✅ **完整的飞书通知 + 声音提醒集成方案**
✅ **10个风险控制模板全部适配声音文件**
✅ **WebSocket实时推送到前端**
✅ **支持自定义声音文件和重复次数**
✅ **用户可在系统管理中配置**

所有代码和文档已准备就绪，可以立即实施！
