# 飞书通知服务测试指南

## 一、前置准备

### 1. 飞书应用信息
- **App ID**: `cli_a9235819f078dcbd`
- **App Secret**: `KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE`
- **应用状态**: 已验证（token获取成功）

### 2. 系统配置状态
- ✅ 后端API正常运行（端口8000）
- ✅ 前端UI正常运行（端口3000）
- ✅ 飞书服务已启用
- ✅ 19个通知模板已加载（包含10个风险控制模板）

## 二、获取飞书接收人ID

### 方法1：使用飞书邮箱（推荐）

如果你的飞书账号绑定了邮箱，可以直接使用邮箱地址作为接收人ID。

**示例**：
```
your.email@company.com
```

### 方法2：获取飞书 Open ID

1. 打开飞书开放平台：https://open.feishu.cn/
2. 登录你的飞书账号
3. 进入"开发者后台" → "应用管理" → 选择你的应用
4. 在"权限管理"中，确保已添加以下权限：
   - `im:message`（发送消息）
   - `im:message:send_as_bot`（以应用身份发消息）
5. 获取用户Open ID的方法：
   - 方法A：使用飞书API `/open-apis/contact/v3/users/batch_get_id` 通过邮箱或手机号查询
   - 方法B：在飞书群聊中@机器人，机器人可以获取到发送者的Open ID

### 方法3：使用飞书机器人测试工具

1. 在飞书开放平台，进入你的应用
2. 点击"机器人" → "调试工具"
3. 使用"发送消息"功能，可以看到你的Open ID

## 三、在系统中测试飞书通知

### 步骤1：访问系统管理页面

打开浏览器，访问：
```
http://13.115.21.77:3000/system
```

使用管理员账号登录：
- 用户名：`admin`
- 密码：`admin123`

### 步骤2：进入通知服务配置

1. 点击顶部导航栏的"通知服务"标签
2. 确认飞书配置状态为"已启用"
3. 确认App ID和App Secret已填写

### 步骤3：发送测试消息

1. 在"测试接收人"输入框中，输入你的飞书接收人ID（邮箱或Open ID）
   - 示例（邮箱）：`your.email@company.com`
   - 示例（Open ID）：`ou_xxxxxxxxxxxxxx`

2. 点击"发送测试消息"按钮

3. 等待发送结果：
   - ✅ 成功：显示"测试消息发送成功！请检查接收端"
   - ❌ 失败：显示具体错误信息

### 步骤4：检查飞书接收

打开你的飞书客户端，查看是否收到测试消息：

**测试消息格式**：
```
标题：🧪 测试消息

内容：
**这是一条测试消息**

如果您收到此消息，说明飞书通知服务配置成功！

测试时间：2026-03-05 21:30:00
```

## 四、使用API直接测试

### 方法1：使用curl命令

```bash
# 1. 获取认证token
TOKEN=$(curl -s -X POST http://13.115.21.77:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | jq -r '.access_token')

# 2. 发送测试消息（使用邮箱）
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/test/feishu?recipient=your.email@company.com" \
  -H "Authorization: Bearer $TOKEN"

# 3. 发送测试消息（使用Open ID）
curl -X POST "http://13.115.21.77:8000/api/v1/notifications/test/feishu?recipient=ou_xxxxxxxxxxxxxx" \
  -H "Authorization: Bearer $TOKEN"
```

### 方法2：使用Python脚本

```python
import requests

# 1. 登录获取token
login_response = requests.post(
    'http://13.115.21.77:8000/api/v1/auth/login',
    json={'username': 'admin', 'password': 'admin123'}
)
token = login_response.json()['access_token']

# 2. 发送测试消息
test_response = requests.post(
    'http://13.115.21.77:8000/api/v1/notifications/test/feishu',
    params={'recipient': 'your.email@company.com'},
    headers={'Authorization': f'Bearer {token}'}
)

print(test_response.json())
```

## 五、验证飞书API凭证

### 直接测试飞书API

```bash
curl -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/ \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "cli_a9235819f078dcbd",
    "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"
  }'
```

**成功响应示例**：
```json
{
  "code": 0,
  "expire": 6530,
  "msg": "ok",
  "tenant_access_token": "t-g104365KGE5HXPGXEYSM6YTZ25N3H5RKWX3NVXJ2"
}
```

## 六、常见问题排查

### 问题1：提示"飞书服务未初始化"

**原因**：飞书配置未保存或未启用

**解决方案**：
1. 确认飞书配置开关为"已启用"
2. 确认App ID和App Secret已填写
3. 点击"保存配置"按钮
4. 等待提示"配置保存成功"

### 问题2：提示"接收人ID无效"

**原因**：接收人ID格式不正确或用户不存在

**解决方案**：
1. 确认使用的是正确的飞书邮箱或Open ID
2. 如果使用邮箱，确认该邮箱已绑定到飞书账号
3. 如果使用Open ID，确认格式为 `ou_` 开头的字符串

### 问题3：提示"权限不足"

**原因**：飞书应用缺少必要权限

**解决方案**：
1. 登录飞书开放平台
2. 进入应用管理 → 权限管理
3. 添加以下权限：
   - `im:message`
   - `im:message:send_as_bot`
4. 保存并发布应用

### 问题4：消息发送成功但未收到

**原因**：可能被飞书消息过滤或应用未添加

**解决方案**：
1. 在飞书中搜索你的应用名称
2. 点击"添加"将应用添加到你的飞书
3. 检查飞书的消息通知设置
4. 查看飞书的"消息助手"或"机器人"列表

### 问题5：Token过期

**原因**：tenant_access_token有效期约1.8小时

**解决方案**：
- 系统会自动刷新token，无需手动处理
- 如果持续失败，尝试重新保存飞书配置

## 七、查看发送日志

### 在UI中查看

1. 访问 http://13.115.21.77:3000/system
2. 点击"通知服务"标签
3. 滚动到"发送日志"部分
4. 可以按服务类型和状态筛选日志

### 使用API查看

```bash
# 获取最近50条日志
curl -X GET "http://13.115.21.77:8000/api/v1/notifications/logs?limit=50" \
  -H "Authorization: Bearer $TOKEN"

# 只查看飞书发送日志
curl -X GET "http://13.115.21.77:8000/api/v1/notifications/logs?service_type=feishu&limit=50" \
  -H "Authorization: Bearer $TOKEN"

# 只查看失败的日志
curl -X GET "http://13.115.21.77:8000/api/v1/notifications/logs?status=failed&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

## 八、风险告警测试

系统已配置10个风险控制模板，使用"生鲜配送语"避免敏感词：

### 模板列表

1. **正向开仓点差提醒** - `forward_open_spread_alert`
2. **正向平仓点差提醒** - `forward_close_spread_alert`
3. **反向开仓点差提醒** - `reverse_open_spread_alert`
4. **反向平仓点差提醒** - `reverse_close_spread_alert`
5. **MT5卡顿提醒** - `mt5_lag_alert`
6. **Binance净资产提醒** - `binance_net_asset_alert`
7. **Bybit净资产提醒** - `bybit_net_asset_alert`
8. **Binance爆仓价提醒** - `binance_liquidation_alert`
9. **Bybit爆仓价提醒** - `bybit_liquidation_alert`
10. **单腿提醒** - `single_leg_alert`

### 触发条件

这些告警会在以下情况自动触发：
- 点差达到设定阈值
- MT5连接异常
- 账户净资产低于预警线
- 价格接近爆仓价
- 出现单边持仓

### 手动测试告警

可以通过API手动发送告警测试：

```bash
curl -X POST http://13.115.21.77:8000/api/v1/notifications/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_key": "forward_open_spread_alert",
    "user_ids": ["0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24"],
    "variables": {
      "spread": "0.35",
      "threshold": "0.30",
      "estimated_profit": "150.00"
    }
  }'
```

## 九、技术支持

如遇到问题，请检查：

1. **后端日志**：`c:\app\hustle2026\backend.log`
2. **浏览器控制台**：F12 → Console标签
3. **网络请求**：F12 → Network标签

或联系系统管理员获取帮助。
