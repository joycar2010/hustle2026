# 快速访问指南 - 通知服务配置

## 问题：无法打开 http://13.115.21.77:3000/system

### 原因
`/system` 路由需要登录认证才能访问（`requiresAuth: true`）

### 解决方案

#### 方法1：通过浏览器访问（推荐）

1. **登录系统**
   ```
   访问: http://13.115.21.77:3000/login
   输入用户名和密码登录
   ```

2. **访问系统管理页面**
   ```
   登录后，访问: http://13.115.21.77:3000/system
   或者在导航菜单中点击"系统管理"
   ```

3. **配置通知服务**
   - 点击"通知服务"标签
   - 配置飞书API（App ID、App Secret、接收者ID）
   - 点击"测试连接"验证配置

4. **配置声音提醒**
   - 点击"提醒设置"标签
   - 上传5种类型的MP3声音文件
   - 设置每种提醒的重复播放次数
   - 点击"保存设置"

#### 方法2：使用API直接配置（无需登录）

如果你有API Token，可以直接通过API配置：

```bash
# 1. 配置飞书通知
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/config/feishu" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "app_id": "cli_a9235819f078dcbd",
    "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE",
    "receiver_id": "YOUR_FEISHU_EMAIL_OR_OPENID"
  }'

# 2. 测试飞书通知
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/test/feishu" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_id": "YOUR_FEISHU_EMAIL_OR_OPENID"
  }'

# 3. 发送测试提醒
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

#### 方法3：临时禁用认证（仅用于测试）

如果需要临时禁用认证进行测试：

```javascript
// 修改 frontend/src/router/index.js
{
  path: '/system',
  name: 'System',
  component: () => import('@/views/System.vue'),
  meta: { requiresAuth: false }  // 改为 false
}
```

**注意**：测试完成后记得改回 `true`

---

## 服务状态检查

### 检查前端服务
```bash
# 检查端口3000是否监听
netstat -ano | grep ":3000"

# 测试前端访问
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/
# 应该返回 200
```

### 检查后端服务
```bash
# 检查端口8000是否监听
netstat -ano | grep ":8000"

# 测试后端API
curl -s http://localhost:8000/docs
# 应该返回API文档页面
```

### 查看服务日志
```bash
# 后端日志
tail -f /c/app/hustle2026/backend.log

# 前端日志
tail -f /c/app/hustle2026/frontend.log
```

---

## 常见问题

### Q1: 登录后仍然无法访问 /system
**A**: 检查浏览器Console是否有错误，可能是组件加载失败

### Q2: 页面显示空白
**A**: 
1. 打开浏览器开发者工具（F12）
2. 查看Console标签是否有错误
3. 查看Network标签检查资源加载情况

### Q3: 飞书通知配置后无法发送
**A**: 
1. 检查App ID和App Secret是否正确
2. 检查接收者ID格式（邮箱或Open ID）
3. 查看后端日志：`tail -f /c/app/hustle2026/backend.log`
4. 查看数据库通知日志：
   ```sql
   SELECT * FROM notification_logs
   ORDER BY created_at DESC
   LIMIT 10;
   ```

### Q4: 声音文件上传失败
**A**: 
1. 确保文件格式为MP3
2. 文件大小 < 500KB
3. 检查 `/c/app/hustle2026/backend/uploads/sounds/` 目录权限

---

## 快速测试流程

1. **登录系统**
   ```
   http://13.115.21.77:3000/login
   ```

2. **访问系统管理**
   ```
   http://13.115.21.77:3000/system
   ```

3. **配置飞书**
   - 通知服务 → 飞书配置
   - 输入App ID、App Secret、接收者ID
   - 点击"测试连接"

4. **上传声音**
   - 提醒设置 → 上传声音文件
   - 设置重复次数
   - 点击"保存设置"

5. **测试通知**
   - 通知服务 → 通知模板
   - 选择一个模板
   - 点击"发送测试"

---

## 联系支持

如果问题仍然存在，请提供：
1. 浏览器Console错误信息
2. 后端日志（最后50行）
3. 访问的具体URL
4. 是否已登录

