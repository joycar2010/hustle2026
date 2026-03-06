# 通知服务快速入门指南

## 一、数据库初始化

### 1. 执行迁移脚本
```bash
# 连接到PostgreSQL数据库
psql -U postgres -d hustle2026

# 执行迁移脚本
\i backend/migrations/notification_service.sql
```

### 2. 验证表创建
```sql
-- 检查表是否创建成功
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name LIKE 'notification%';

-- 应该看到：
-- notification_configs
-- notification_templates
-- notification_logs
-- user_notification_settings
```

---

## 二、后端配置

### 1. 启动飞书服务

在应用启动时初始化飞书服务（已自动集成到main.py）：

```python
# backend/app/main.py
from app.services.feishu_service import init_feishu_service

@app.on_event("startup")
async def startup_event():
    # 从数据库加载飞书配置
    async with get_db_context() as db:
        result = await db.execute(
            select(NotificationConfig).filter(
                NotificationConfig.service_type == "feishu",
                NotificationConfig.is_enabled == True
            )
        )
        config = result.scalar_one_or_none()

        if config:
            init_feishu_service(
                config.config_data.get("app_id"),
                config.config_data.get("app_secret")
            )
```

### 2. 重启后端服务
```bash
cd backend
python -m uvicorn app.main:app --reload
```

---

## 三、前端配置

### 1. 访问系统管理页面
```
http://13.115.21.77:3000/system
```

### 2. 配置飞书服务

1. 点击"通知服务"标签
2. 在"飞书配置"中填写：
   - App ID: `cli_a9235819f078dcbd`
   - App Secret: `KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE`
3. 启用开关
4. 点击"保存配置"

### 3. 测试飞书通知

1. 在"测试接收人"输入框填写飞书用户的邮箱或open_id
2. 点击"发送测试消息"
3. 检查飞书是否收到测试消息

---

## 四、使用示例

### 1. 在代码中发送通知

```python
# 在策略执行后发送通知
from app.api.v1.notifications import send_notification

# 发送交易完成通知
await send_notification(
    SendNotificationRequest(
        template_key="trade_executed",
        user_ids=[str(user_id)],
        variables={
            "order_id": "ORD20260305001",
            "product_name": "优质商品A",
            "quantity": "10",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    ),
    current_user=current_user,
    db=db
)
```

### 2. 发送风险预警

```python
# 余额不足预警
await send_notification(
    SendNotificationRequest(
        template_key="balance_alert",
        user_ids=[str(user_id)],
        variables={
            "balance": "5000",
            "recommend_amount": "10000"
        }
    ),
    current_user=current_user,
    db=db
)
```

### 3. 批量发送系统通知

```python
# 系统维护通知（发送给所有用户）
user_ids = [str(u.user_id) for u in all_users]

await send_notification(
    SendNotificationRequest(
        template_key="system_maintenance",
        user_ids=user_ids,
        variables={
            "maintenance_time": "2026-03-06 02:00-04:00",
            "maintenance_content": "系统升级维护",
            "estimated_recovery": "2026-03-06 04:00"
        }
    ),
    current_user=current_user,
    db=db
)
```

---

## 五、自定义通知模板

### 1. 在前端编辑模板

1. 进入"通知服务" → "通知模板"标签
2. 找到要编辑的模板，点击"编辑"
3. 修改标题模板和内容模板
4. 选择通知渠道（飞书/邮件/短信）
5. 设置优先级
6. 保存

### 2. 模板变量说明

模板支持使用 `{变量名}` 格式的变量：

```
标题模板：🚚 您的订单已配送完成
内容模板：
订单编号：{order_id}
商品名称：{product_name}
配送数量：{quantity}件
配送时间：{time}
```

发送时传入变量：
```python
variables={
    "order_id": "ORD001",
    "product_name": "商品A",
    "quantity": "10",
    "time": "2026-03-05 14:30:00"
}
```

---

## 六、查看发送日志

### 1. 在前端查看

1. 进入"通知服务" → "发送日志"标签
2. 可按服务类型、状态筛选
3. 查看发送详情和错误信息

### 2. 通过API查询

```bash
# 查询最近50条日志
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/v1/notifications/logs?limit=50"

# 查询失败的日志
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/v1/notifications/logs?status=failed"
```

---

## 七、常见问题

### Q1: 飞书消息发送失败？

**检查清单**：
1. App ID和App Secret是否正确
2. 飞书服务是否已启用
3. 接收人ID是否正确（open_id或邮箱）
4. 查看后端日志错误信息

### Q2: 如何获取飞书用户的open_id？

**方法1**：通过飞书开放平台
1. 登录飞书开放平台
2. 进入"通讯录管理"
3. 查看用户信息

**方法2**：使用邮箱作为receive_id_type
```python
await feishu.send_card_message(
    receive_id="user@example.com",
    title="测试",
    content="内容",
    receive_id_type="email"  # 使用邮箱
)
```

### Q3: 如何添加新的通知模板？

```sql
INSERT INTO notification_templates (
    template_key,
    template_name,
    category,
    title_template,
    content_template,
    enable_feishu,
    priority
) VALUES (
    'custom_alert',
    '自定义提醒',
    'system',
    '⚠️ {title}',
    '{content}',
    true,
    2
);
```

### Q4: 如何禁用某个通知模板？

```sql
UPDATE notification_templates
SET is_active = false
WHERE template_key = 'trade_executed';
```

---

## 八、API文档

### 1. 获取通知配置
```
GET /api/v1/notifications/config
```

### 2. 更新通知配置
```
PUT /api/v1/notifications/config/{service_type}
Body: {
  "is_enabled": true,
  "config_data": {...}
}
```

### 3. 测试通知服务
```
POST /api/v1/notifications/test/{service_type}?recipient=xxx
```

### 4. 获取通知模板
```
GET /api/v1/notifications/templates?category=trading
```

### 5. 更新通知模板
```
PUT /api/v1/notifications/templates/{template_id}
Body: {
  "title_template": "...",
  "content_template": "...",
  "priority": 3
}
```

### 6. 发送通知
```
POST /api/v1/notifications/send
Body: {
  "template_key": "trade_executed",
  "user_ids": ["uuid1", "uuid2"],
  "variables": {
    "order_id": "ORD001",
    "quantity": "10"
  }
}
```

### 7. 查询发送日志
```
GET /api/v1/notifications/logs?service_type=feishu&status=sent&limit=50
```

---

## 九、生鲜配送语词汇表

| 交易术语 | 生鲜配送语 | 使用场景 |
|---------|-----------|---------|
| 开仓 | 接收订单 | 新建持仓 |
| 平仓 | 配送完成 | 关闭持仓 |
| 持仓 | 库存 | 当前持仓 |
| 盈亏 | 配送结果 | 盈亏情况 |
| 余额 | 账户余额 | 账户资金 |
| 保证金 | 预付款 | 保证金 |
| 强平 | 库存清理 | 强制平仓 |
| 爆仓 | 库存不足 | 爆仓风险 |
| 套利 | 配送优化 | 套利策略 |
| 对冲 | 双向配送 | 对冲操作 |

---

## 十、下一步

1. ✅ 配置飞书服务
2. ✅ 测试消息发送
3. ⏳ 集成到交易流程
4. ⏳ 实现邮件服务
5. ⏳ 实现短信服务
6. ⏳ 添加用户通知偏好设置

---

## 技术支持

如有问题，请查看：
- 后端日志：`backend/logs/app.log`
- 飞书开放平台文档：https://open.feishu.cn/document/
- 系统管理页面：http://13.115.21.77:3000/system
