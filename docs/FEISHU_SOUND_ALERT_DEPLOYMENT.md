# 飞书通知与声音提醒集成 - 快速部署指南

## 已完成的工作 ✅

### 一、后端修改

1. **risk_alert_service.py** - 添加WebSocket广播功能
   - 导入 `connection_manager`
   - 在 `_send_alert` 方法中添加前端广播调用
   - 新增 `_broadcast_alert_to_frontend` 方法

2. **spread_alert_service.py** - 添加WebSocket广播功能
   - 导入 `connection_manager`
   - 在飞书发送成功后广播到前端
   - 新增 `_broadcast_alert_to_frontend` 方法

### 二、前端修改

1. **market.js** - 添加 `risk_alert` 消息处理
   - 在 `ws.onmessage` 中添加 `risk_alert` 类型处理
   - 动态导入 `notificationStore` 避免循环依赖
   - 构造 alert 对象并触发弹窗和声音

2. **notification.js** - 声音播放逻辑（已存在，无需修改）
   - 已支持所有提醒类型的声音映射
   - 已支持自定义声音文件和重复次数

---

## 部署步骤

### 步骤1：执行数据库迁移

```bash
# 添加10个风险控制提醒模板
psql -U postgres -d hustle2026 -f backend/migrations/add_spread_alert_templates.sql
```

**验证**：
```sql
SELECT template_key, template_name, enable_feishu
FROM notification_templates
WHERE template_key IN (
    'forward_open_spread_alert',
    'mt5_lag_alert',
    'binance_net_asset_alert',
    'single_leg_alert'
);
-- 应该看到10条记录
```

### 步骤2：重启后端服务

```bash
# 重启FastAPI后端
cd backend
# 如果使用systemd
sudo systemctl restart hustle-backend

# 或者如果使用PM2
pm2 restart hustle-backend

# 或者直接运行
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 步骤3：重启前端服务

```bash
# 重新构建前端
cd frontend
npm run build

# 如果使用nginx，重启nginx
sudo systemctl restart nginx

# 或者开发模式
npm run dev
```

### 步骤4：配置飞书通知

1. 访问 http://13.115.21.77:3000/system
2. 点击"通知服务"标签
3. 配置飞书API：
   - App ID: `cli_a9235819f078dcbd`
   - App Secret: `KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE`
   - 接收者ID: 用户的飞书邮箱或Open ID
4. 点击"测试连接"验证配置

### 步骤5：配置声音文件

1. 访问 http://13.115.21.77:3000/system
2. 点击"提醒设置"标签
3. 为每种提醒类型上传MP3声音文件：
   - 单腿交易提醒
   - 点差提醒
   - 净资产提醒
   - MT5卡顿提醒
   - 爆仓价提醒
4. 设置每种提醒的重复播放次数（1-10次）
5. 点击"保存设置"

---

## 测试验证

### 测试1：点差提醒

```bash
# 发送测试通知
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/send" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "forward_open_spread_alert",
    "user_ids": ["YOUR_USER_ID"],
    "variables": {
      "spread": "2.50",
      "threshold": "2.00",
      "market_status": "优惠价格出现",
      "estimated_profit": "25.00"
    }
  }'
```

**预期结果**：
- ✅ 飞书收到卡片消息："💰 优惠价格机会提醒"
- ✅ 前端显示弹窗提醒
- ✅ 播放点差提醒声音（重复设定次数）

### 测试2：MT5卡顿提醒

```bash
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/send" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "mt5_lag_alert",
    "user_ids": ["YOUR_USER_ID"],
    "variables": {
      "failure_count": "3",
      "last_response_time": "2026-03-05 10:30:15"
    }
  }'
```

**预期结果**：
- ✅ 飞书收到卡片消息："⚠️ 配送系统延迟提醒"
- ✅ 前端显示弹窗提醒
- ✅ 播放MT5提醒声音（重复设定次数）

### 测试3：净资产提醒

```bash
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/send" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "binance_net_asset_alert",
    "user_ids": ["YOUR_USER_ID"],
    "variables": {
      "current_asset": "8500.00",
      "threshold": "10000.00",
      "status": "低于"
    }
  }'
```

**预期结果**：
- ✅ 飞书收到卡片消息："💰 A仓库资产预警"
- ✅ 前端显示弹窗提醒
- ✅ 播放净资产提醒声音（重复设定次数）

### 测试4：WebSocket连接

打开浏览器Console：

```javascript
// 检查WebSocket连接状态
import { useMarketStore } from '@/stores/market'
const marketStore = useMarketStore()
console.log('WebSocket connected:', marketStore.connected)

// 监听WebSocket消息
watch(() => marketStore.lastMessage, (msg) => {
  if (msg.type === 'risk_alert') {
    console.log('收到风险提醒:', msg.data)
  }
})
```

---

## 故障排查

### 问题1：飞书通知未收到

**检查**：
1. 飞书配置是否正确（App ID、App Secret）
2. 接收者ID是否正确（邮箱或Open ID）
3. 查看后端日志：`tail -f backend/logs/app.log`
4. 查看通知日志表：
   ```sql
   SELECT * FROM notification_logs
   ORDER BY created_at DESC
   LIMIT 10;
   ```

### 问题2：前端未播放声音

**检查**：
1. WebSocket是否连接：浏览器Console查看 `marketStore.connected`
2. 声音开关是否启用：localStorage中的 `alertSoundEnabled`
3. 声音文件是否上传：System页面查看声音文件路径
4. 浏览器是否允许自动播放：某些浏览器需要用户交互后才能播放音频

**解决方法**：
```javascript
// 在浏览器Console中手动测试声音播放
const audio = new Audio('/sounds/hello-moto.mp3')
audio.play()
```

### 问题3：WebSocket消息未接收

**检查**：
1. 后端WebSocket服务是否运行
2. 前端是否正确连接WebSocket
3. 查看Network标签中的WS连接
4. 查看后端日志中的WebSocket广播日志

**调试**：
```javascript
// 在market.js的onmessage中添加日志
ws.onmessage = (event) => {
  console.log('WebSocket message received:', event.data)
  // ... 现有代码
}
```

### 问题4：声音文件404错误

**检查**：
1. 声音文件是否正确上传到 `/uploads/sounds/` 目录
2. 文件路径是否正确（应该是 `/uploads/sounds/filename.mp3`）
3. Nginx配置是否正确映射 `/uploads/` 路径

**Nginx配置示例**：
```nginx
location /uploads/ {
    alias /path/to/backend/uploads/;
    autoindex off;
}
```

---

## 监控和日志

### 查看通知发送日志

```sql
-- 查看最近的通知记录
SELECT
    template_key,
    recipient,
    status,
    sent_at,
    error_message
FROM notification_logs
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC;

-- 统计各类型通知的发送情况
SELECT
    template_key,
    status,
    COUNT(*) as count
FROM notification_logs
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY template_key, status
ORDER BY template_key, status;
```

### 查看后端日志

```bash
# 实时查看日志
tail -f backend/logs/app.log | grep -E "Alert|WebSocket|Feishu"

# 查看最近的错误
tail -n 100 backend/logs/app.log | grep ERROR
```

### 前端调试

```javascript
// 在浏览器Console中
// 1. 查看notification store状态
import { useNotificationStore } from '@/stores/notification'
const notificationStore = useNotificationStore()
console.log('Alerts:', notificationStore.alerts)
console.log('Alert settings:', notificationStore.alertSettings)
console.log('Sound enabled:', notificationStore.alertSoundEnabled)

// 2. 手动触发测试提醒
notificationStore.triggerPopup({
  id: Date.now(),
  type: 'forward_open',
  level: 'warning',
  title: '测试提醒',
  message: '这是一条测试消息',
  timestamp: new Date().toISOString()
})
```

---

## 性能优化建议

### 1. 冷却时间控制

- 默认60秒冷却时间，避免频繁通知
- 可在数据库中调整 `cooldown_seconds` 字段

```sql
-- 调整冷却时间为2分钟
UPDATE notification_templates
SET cooldown_seconds = 120
WHERE template_key LIKE '%alert%';
```

### 2. WebSocket消息压缩

如果消息量大，可以考虑启用WebSocket压缩：

```python
# backend/app/main.py
from fastapi import FastAPI
app = FastAPI()

# 启用WebSocket压缩
app.add_middleware(
    WebSocketCompressionMiddleware,
    compression_level=6
)
```

### 3. 声音文件优化

- 使用MP3格式（兼容性好）
- 文件大小 < 500KB
- 时长 2-5秒
- 比特率 128kbps

---

## 下一步

### 立即执行
- [x] 执行数据库迁移
- [x] 重启后端服务
- [x] 重启前端服务
- [ ] 配置飞书通知
- [ ] 上传声音文件
- [ ] 测试所有提醒类型

### 后续优化
- [ ] 添加提醒统计分析
- [ ] 支持自定义提醒规则
- [ ] 添加静音时段设置
- [ ] 支持多语言提醒
- [ ] 添加提醒历史记录

---

## 相关文档

- [飞书通知与声音提醒集成方案](FEISHU_SOUND_ALERT_INTEGRATION.md)
- [风险控制提醒功能总结](RISK_ALERT_SUMMARY.md)
- [通知服务实施方案](NOTIFICATION_SERVICE_IMPLEMENTATION.md)

---

## 总结

✅ **后端已添加WebSocket广播功能**
✅ **前端已添加risk_alert消息处理**
✅ **10个风险控制模板全部支持飞书+声音提醒**
✅ **完整的测试和故障排查指南**

所有代码已完成，可以立即部署使用！
