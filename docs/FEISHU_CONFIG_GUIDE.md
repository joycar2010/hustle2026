# 飞书服务配置指南

## 问题说明

当前错误：`飞书服务未配置 (400 Bad Request)`

这是因为飞书服务需要配置 App ID 和 App Secret 才能使用。

## 解决方案

### 方式1: 通过系统管理页面配置（推荐）

1. **登录系统**
   - 访问：http://13.115.21.77:3000
   - 使用管理员账号登录

2. **进入系统管理**
   - 点击左侧导航栏的"系统管理"或访问：http://13.115.21.77:3000/system

3. **配置飞书服务**
   - 找到"通知服务配置"部分
   - 选择"飞书"标签
   - 填写以下信息：
     - **App ID**: `cli_a9235819f078dcbd`
     - **App Secret**: `KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE`
   - 勾选"启用飞书服务"
   - 点击"保存配置"

### 方式2: 通过API直接配置

使用以下curl命令配置飞书服务：

```bash
curl -X PUT "http://13.115.21.77:8000/api/v1/notifications/config/feishu" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "is_enabled": true,
    "config_data": {
      "app_id": "cli_a9235819f078dcbd",
      "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"
    }
  }'
```

### 方式3: 直接更新数据库

如果无法通过前端或API配置，可以直接更新数据库：

```sql
-- 连接到数据库
psql -U postgres -d trading_system

-- 更新飞书配置
UPDATE notification_config
SET
  is_enabled = true,
  config_data = '{"app_id": "cli_a9235819f078dcbd", "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"}'::jsonb,
  updated_at = NOW()
WHERE service_type = 'feishu';

-- 如果记录不存在，插入新记录
INSERT INTO notification_config (config_id, service_type, is_enabled, config_data, created_at, updated_at)
VALUES (
  gen_random_uuid(),
  'feishu',
  true,
  '{"app_id": "cli_a9235819f078dcbd", "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"}'::jsonb,
  NOW(),
  NOW()
)
ON CONFLICT (service_type) DO UPDATE
SET
  is_enabled = EXCLUDED.is_enabled,
  config_data = EXCLUDED.config_data,
  updated_at = EXCLUDED.updated_at;
```

## 获取飞书凭证

如果需要使用自己的飞书应用：

1. **登录飞书开放平台**
   - 访问：https://open.feishu.cn/
   - 使用飞书账号登录

2. **创建企业自建应用**
   - 进入"开发者后台"
   - 点击"创建企业自建应用"
   - 填写应用名称和描述

3. **获取凭证**
   - 在应用详情页面找到"凭证与基础信息"
   - 复制 **App ID** 和 **App Secret**

4. **配置权限**
   需要开通以下权限：
   - `im:message` - 发送消息
   - `im:message:send_as_bot` - 以应用身份发消息
   - `contact:user.base:readonly` - 获取用户基本信息
   - `drive:drive` - 云文档权限（用于上传文件）

5. **配置事件订阅（可选）**
   - 如需接收飞书事件，配置回调URL
   - 回调URL示例：`http://your-domain.com/api/v1/feishu/callback`

## 验证配置

配置完成后，可以通过以下方式验证：

### 1. 测试飞书消息发送

```bash
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/test/feishu?recipient=ou_YOUR_OPEN_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 2. 查看配置状态

```bash
curl -X GET "http://13.115.21.77:8000/api/v1/notifications/config" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3. 同步声音文件到飞书

配置成功后，可以同步声音文件：

```bash
curl -X POST "http://13.115.21.77:8000/api/v1/sounds/sync-to-feishu" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 常见问题

### Q1: 提示"飞书服务未配置"

**原因**：数据库中没有飞书配置或配置未启用

**解决**：按照上述方式1、2或3进行配置

### Q2: 提示"获取飞书token失败"

**原因**：App ID 或 App Secret 不正确

**解决**：
1. 检查配置的凭证是否正确
2. 确认飞书应用状态是否正常
3. 查看后端日志获取详细错误信息

### Q3: 消息发送失败

**原因**：可能是权限不足或接收者ID不正确

**解决**：
1. 确认应用已开通消息发送权限
2. 确认接收者的 open_id 正确
3. 检查用户是否在应用可见范围内

### Q4: 文件上传失败

**原因**：可能是文件格式不支持或权限不足

**解决**：
1. 确认应用已开通云文档权限
2. 检查文件格式（支持：mp3, wav, ogg, opus）
3. 确认文件大小不超过限制（通常20MB）

## 后端日志查看

如果遇到问题，可以查看后端日志：

```bash
# 查看实时日志
tail -f /path/to/backend/logs/app.log

# 或者查看Docker日志（如果使用Docker）
docker logs -f trading-backend
```

## 相关文档

- [飞书开放平台文档](https://open.feishu.cn/document/)
- [飞书消息发送API](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create)
- [飞书文件上传API](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/file/create)

## 技术支持

如有其他问题，请联系开发团队或查看系统日志获取详细错误信息。
