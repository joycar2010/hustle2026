# 通知服务系统实施方案

## 一、系统概述

在系统管理中新增通知服务功能，支持邮件、短信和飞书三种通知渠道，使用"生鲜商品配送语"规避敏感词汇。

**飞书凭证**：
- App ID: `cli_a9235819f078dcbd`
- App Secret: `KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE`

---

## 二、数据库设计

### 1. 通知配置表 (notification_configs)
```sql
CREATE TABLE notification_configs (
    config_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_type VARCHAR(50) UNIQUE NOT NULL,  -- email, sms, feishu
    is_enabled BOOLEAN DEFAULT FALSE,
    config_data JSONB NOT NULL,  -- 服务配置
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 示例数据
INSERT INTO notification_configs (service_type, is_enabled, config_data) VALUES
('feishu', true, '{"app_id": "cli_a9235819f078dcbd", "app_secret": "KPqZCcek8WLYh4rfR0Ec4fq3gkpmTgLE"}'),
('email', false, '{"smtp_host": "smtp.gmail.com", "smtp_port": 587, "username": "", "password": ""}'),
('sms', false, '{"provider": "aliyun", "access_key": "", "access_secret": ""}');
```

### 2. 通知模板表 (notification_templates)
```sql
CREATE TABLE notification_templates (
    template_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_key VARCHAR(100) UNIQUE NOT NULL,
    template_name VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL,  -- trading, risk, system

    -- 生鲜商品配送语模板
    title_template VARCHAR(500) NOT NULL,
    content_template TEXT NOT NULL,

    -- 通知渠道
    enable_email BOOLEAN DEFAULT FALSE,
    enable_sms BOOLEAN DEFAULT FALSE,
    enable_feishu BOOLEAN DEFAULT TRUE,

    -- 优先级和频率控制
    priority INTEGER DEFAULT 1,  -- 1=low, 2=medium, 3=high, 4=urgent
    cooldown_seconds INTEGER DEFAULT 0,

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 示例模板（生鲜商品配送语）
INSERT INTO notification_templates (template_key, template_name, category, title_template, content_template, enable_feishu, priority) VALUES
('trade_executed', '订单配送完成', 'trading',
 '🚚 您的订单已配送完成',
 '订单编号：{order_id}\n商品名称：{product_name}\n配送数量：{quantity}件\n配送时间：{time}\n配送状态：✅ 已签收',
 true, 2),

('balance_alert', '账户余额提醒', 'risk',
 '⚠️ 账户余额不足提醒',
 '尊敬的客户，您的账户余额已低于安全线\n当前余额：{balance}元\n建议充值：{recommend_amount}元\n请及时处理，避免影响配送服务',
 true, 3),

('position_opened', '新订单已接收', 'trading',
 '📦 新订单已接收',
 '订单类型：{order_type}\n商品规格：{specification}\n订单数量：{quantity}件\n预计配送时间：{estimated_time}',
 true, 2),

('position_closed', '订单已完成', 'trading',
 '✅ 订单配送完成',
 '订单编号：{order_id}\n配送结果：{result}\n实际数量：{actual_quantity}件\n客户评价：{feedback}',
 true, 2),

('risk_warning', '库存预警', 'risk',
 '⚠️ 库存预警通知',
 '商品名称：{product_name}\n当前库存：{current_stock}件\n预警阈值：{threshold}件\n建议补货：{recommend_restock}件',
 true, 4),

('system_maintenance', '系统维护通知', 'system',
 '🔧 系统维护通知',
 '维护时间：{maintenance_time}\n维护内容：{maintenance_content}\n预计恢复：{estimated_recovery}\n如有疑问请联系客服',
 true, 3);
```

### 3. 通知日志表 (notification_logs)
```sql
CREATE TABLE notification_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id),
    template_key VARCHAR(100) NOT NULL,
    service_type VARCHAR(50) NOT NULL,
    recipient VARCHAR(500) NOT NULL,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(50) NOT NULL,  -- pending, sent, failed
    error_message TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_notification_logs_user ON notification_logs(user_id);
CREATE INDEX idx_notification_logs_created ON notification_logs(created_at);
```

### 4. 用户通知配置表 (user_notification_settings)
```sql
CREATE TABLE user_notification_settings (
    setting_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) UNIQUE NOT NULL,

    -- 飞书配置
    feishu_user_id VARCHAR(200),  -- 飞书open_id
    feishu_enabled BOOLEAN DEFAULT TRUE,

    -- 邮件配置
    email VARCHAR(200),
    email_enabled BOOLEAN DEFAULT FALSE,

    -- 短信配置
    phone VARCHAR(50),
    sms_enabled BOOLEAN DEFAULT FALSE,

    -- 通知类型开关
    enable_trade_notifications BOOLEAN DEFAULT TRUE,
    enable_risk_notifications BOOLEAN DEFAULT TRUE,
    enable_system_notifications BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 三、后端API实现

### 1. 通知配置API (`/api/v1/notifications/config`)

```python
# backend/app/api/v1/notifications.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.notification_config import NotificationConfig, NotificationTemplate
from app.services.feishu_service import get_feishu_service, init_feishu_service

router = APIRouter()

@router.get("/config")
async def get_notification_configs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取所有通知服务配置"""
    # 需要管理员权限
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    result = await db.execute(select(NotificationConfig))
    configs = result.scalars().all()

    return {
        "success": True,
        "configs": [
            {
                "service_type": c.service_type,
                "is_enabled": c.is_enabled,
                "config_data": c.config_data
            }
            for c in configs
        ]
    }

@router.put("/config/{service_type}")
async def update_notification_config(
    service_type: str,
    config_data: dict,
    is_enabled: bool,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新通知服务配置"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # 查找或创建配置
    result = await db.execute(
        select(NotificationConfig).filter(
            NotificationConfig.service_type == service_type
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        config = NotificationConfig(
            service_type=service_type,
            is_enabled=is_enabled,
            config_data=config_data
        )
        db.add(config)
    else:
        config.is_enabled = is_enabled
        config.config_data = config_data
        config.updated_at = datetime.utcnow()

    await db.commit()

    # 如果是飞书配置，重新初始化服务
    if service_type == "feishu" and is_enabled:
        init_feishu_service(
            config_data.get("app_id"),
            config_data.get("app_secret")
        )

    return {"success": True, "message": "配置已更新"}

@router.post("/test/{service_type}")
async def test_notification_service(
    service_type: str,
    recipient: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """测试通知服务"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    if service_type == "feishu":
        feishu = get_feishu_service()
        if not feishu:
            raise HTTPException(status_code=400, detail="飞书服务未初始化")

        result = await feishu.send_text_message(
            receive_id=recipient,
            content="🧪 这是一条测试消息\n\n如果您收到此消息，说明飞书通知服务配置成功！"
        )

        return result

    elif service_type == "email":
        # TODO: 实现邮件测试
        return {"success": False, "error": "邮件服务暂未实现"}

    elif service_type == "sms":
        # TODO: 实现短信测试
        return {"success": False, "error": "短信服务暂未实现"}

    else:
        raise HTTPException(status_code=400, detail="不支持的服务类型")
```

### 2. 通知模板API (`/api/v1/notifications/templates`)

```python
@router.get("/templates")
async def get_notification_templates(
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取通知模板列表"""
    query = select(NotificationTemplate).filter(
        NotificationTemplate.is_active == True
    )

    if category:
        query = query.filter(NotificationTemplate.category == category)

    result = await db.execute(query)
    templates = result.scalars().all()

    return {
        "success": True,
        "templates": [
            {
                "template_id": str(t.template_id),
                "template_key": t.template_key,
                "template_name": t.template_name,
                "category": t.category,
                "title_template": t.title_template,
                "content_template": t.content_template,
                "enable_email": t.enable_email,
                "enable_sms": t.enable_sms,
                "enable_feishu": t.enable_feishu,
                "priority": t.priority
            }
            for t in templates
        ]
    }

@router.put("/templates/{template_id}")
async def update_notification_template(
    template_id: str,
    template_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新通知模板"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    result = await db.execute(
        select(NotificationTemplate).filter(
            NotificationTemplate.template_id == uuid.UUID(template_id)
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    # 更新模板字段
    for key, value in template_data.items():
        if hasattr(template, key):
            setattr(template, key, value)

    template.updated_at = datetime.utcnow()
    await db.commit()

    return {"success": True, "message": "模板已更新"}
```

### 3. 发送通知API (`/api/v1/notifications/send`)

```python
@router.post("/send")
async def send_notification(
    template_key: str,
    user_ids: List[str],
    variables: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """发送通知"""
    # 获取模板
    result = await db.execute(
        select(NotificationTemplate).filter(
            NotificationTemplate.template_key == template_key,
            NotificationTemplate.is_active == True
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    # 渲染模板
    title = template.title_template.format(**variables)
    content = template.content_template.format(**variables)

    # 获取用户通知设置
    results = []
    for user_id in user_ids:
        user_result = await db.execute(
            select(UserNotificationSettings).filter(
                UserNotificationSettings.user_id == uuid.UUID(user_id)
            )
        )
        user_settings = user_result.scalar_one_or_none()

        if not user_settings:
            continue

        # 发送飞书通知
        if template.enable_feishu and user_settings.feishu_enabled and user_settings.feishu_user_id:
            feishu = get_feishu_service()
            if feishu:
                result = await feishu.send_card_message(
                    receive_id=user_settings.feishu_user_id,
                    title=title,
                    content=content,
                    color="blue" if template.priority <= 2 else "orange" if template.priority == 3 else "red"
                )

                # 记录日志
                log = NotificationLog(
                    user_id=uuid.UUID(user_id),
                    template_key=template_key,
                    service_type="feishu",
                    recipient=user_settings.feishu_user_id,
                    title=title,
                    content=content,
                    status="sent" if result.get("success") else "failed",
                    error_message=result.get("error"),
                    sent_at=datetime.utcnow() if result.get("success") else None
                )
                db.add(log)
                results.append(result)

    await db.commit()

    return {
        "success": True,
        "sent_count": sum(1 for r in results if r.get("success")),
        "failed_count": sum(1 for r in results if not r.get("success")),
        "results": results
    }
```

---

## 四、前端实现

### 1. 系统管理页面 - 通知服务配置

在 `frontend/src/views/System.vue` 中添加通知服务配置标签页：

```vue
<template>
  <div class="notification-config">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="飞书配置" name="feishu">
        <el-form :model="feishuConfig" label-width="120px">
          <el-form-item label="启用状态">
            <el-switch v-model="feishuConfig.is_enabled" />
          </el-form-item>
          <el-form-item label="App ID">
            <el-input v-model="feishuConfig.app_id" placeholder="cli_a9235819f078dcbd" />
          </el-form-item>
          <el-form-item label="App Secret">
            <el-input v-model="feishuConfig.app_secret" type="password" show-password />
          </el-form-item>
          <el-form-item label="测试接收人">
            <el-input v-model="testRecipient" placeholder="飞书open_id" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveConfig('feishu')">保存配置</el-button>
            <el-button @click="testNotification('feishu')">发送测试消息</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="邮件配置" name="email">
        <!-- 邮件配置表单 -->
      </el-tab-pane>

      <el-tab-pane label="短信配置" name="sms">
        <!-- 短信配置表单 -->
      </el-tab-pane>

      <el-tab-pane label="通知模板" name="templates">
        <el-table :data="templates" style="width: 100%">
          <el-table-column prop="template_name" label="模板名称" />
          <el-table-column prop="category" label="分类" />
          <el-table-column label="通知渠道">
            <template #default="{ row }">
              <el-tag v-if="row.enable_feishu" type="success" size="small">飞书</el-tag>
              <el-tag v-if="row.enable_email" type="info" size="small">邮件</el-tag>
              <el-tag v-if="row.enable_sms" type="warning" size="small">短信</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button size="small" @click="editTemplate(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { ElMessage } from 'element-plus'

const activeTab = ref('feishu')
const feishuConfig = ref({
  is_enabled: false,
  app_id: 'cli_a9235819f078dcbd',
  app_secret: ''
})
const testRecipient = ref('')
const templates = ref([])

onMounted(async () => {
  await loadConfigs()
  await loadTemplates()
})

async function loadConfigs() {
  try {
    const response = await api.get('/api/v1/notifications/config')
    const configs = response.data.configs

    const feishu = configs.find(c => c.service_type === 'feishu')
    if (feishu) {
      feishuConfig.value = {
        is_enabled: feishu.is_enabled,
        app_id: feishu.config_data.app_id,
        app_secret: feishu.config_data.app_secret
      }
    }
  } catch (error) {
    ElMessage.error('加载配置失败')
  }
}

async function loadTemplates() {
  try {
    const response = await api.get('/api/v1/notifications/templates')
    templates.value = response.data.templates
  } catch (error) {
    ElMessage.error('加载模板失败')
  }
}

async function saveConfig(serviceType) {
  try {
    await api.put(`/api/v1/notifications/config/${serviceType}`, {
      is_enabled: feishuConfig.value.is_enabled,
      config_data: {
        app_id: feishuConfig.value.app_id,
        app_secret: feishuConfig.value.app_secret
      }
    })
    ElMessage.success('配置保存成功')
  } catch (error) {
    ElMessage.error('配置保存失败')
  }
}

async function testNotification(serviceType) {
  if (!testRecipient.value) {
    ElMessage.warning('请输入测试接收人')
    return
  }

  try {
    const response = await api.post(`/api/v1/notifications/test/${serviceType}`, {
      recipient: testRecipient.value
    })

    if (response.data.success) {
      ElMessage.success('测试消息发送成功')
    } else {
      ElMessage.error(`发送失败: ${response.data.error}`)
    }
  } catch (error) {
    ElMessage.error('发送测试消息失败')
  }
}
</script>
```

---

## 五、权限配置

在 `backend/app/models/permission.py` 中添加通知管理权限：

```python
# 通知管理权限
NOTIFICATION_PERMISSIONS = [
    {
        "code": "notification:config:view",
        "name": "查看通知配置",
        "category": "notification"
    },
    {
        "code": "notification:config:edit",
        "name": "编辑通知配置",
        "category": "notification"
    },
    {
        "code": "notification:template:view",
        "name": "查看通知模板",
        "category": "notification"
    },
    {
        "code": "notification:template:edit",
        "name": "编辑通知模板",
        "category": "notification"
    },
    {
        "code": "notification:send",
        "name": "发送通知",
        "category": "notification"
    }
]
```

---

## 六、使用示例

### 1. 交易执行后发送通知

```python
# 在策略执行后
from app.services.notification_service import send_notification

await send_notification(
    template_key="trade_executed",
    user_ids=[str(user_id)],
    variables={
        "order_id": "ORD20260305001",
        "product_name": "优质商品A",
        "quantity": "10",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
)
```

### 2. 风险预警通知

```python
await send_notification(
    template_key="balance_alert",
    user_ids=[str(user_id)],
    variables={
        "balance": "5000",
        "recommend_amount": "10000"
    }
)
```

---

## 七、生鲜商品配送语模板示例

| 交易术语 | 生鲜配送语 | 示例 |
|---------|-----------|------|
| 开仓 | 接收订单 | "📦 新订单已接收" |
| 平仓 | 配送完成 | "✅ 订单配送完成" |
| 持仓 | 库存 | "当前库存：100件" |
| 盈亏 | 配送结果 | "配送结果：优秀" |
| 余额 | 账户余额 | "账户余额：10000元" |
| 保证金 | 预付款 | "预付款：5000元" |
| 强平 | 库存清理 | "⚠️ 库存清理通知" |
| 爆仓 | 库存不足 | "❌ 库存不足预警" |

---

## 八、实施步骤

1. **数据库迁移**（10分钟）
   - 执行SQL创建新表
   - 插入初始配置和模板

2. **后端实现**（2-3小时）
   - 创建模型文件
   - 实现飞书服务
   - 创建API端点

3. **前端实现**（2-3小时）
   - 添加系统管理页面标签
   - 实现配置界面
   - 实现模板管理

4. **权限配置**（30分钟）
   - 添加权限定义
   - 分配给管理员角色

5. **测试验证**（1小时）
   - 测试飞书消息发送
   - 测试模板渲染
   - 测试权限控制

**总计时间**：6-8小时

---

## 九、注意事项

1. **飞书凭证安全**：App Secret应加密存储
2. **频率限制**：避免短时间大量发送消息
3. **错误处理**：记录发送失败日志
4. **用户隐私**：通知内容不包含敏感信息
5. **模板审核**：确保生鲜配送语合理规避敏感词

---

## 十、后续优化

1. 实现邮件和短信服务
2. 添加通知统计和分析
3. 支持通知模板变量预览
4. 实现通知发送队列（异步处理）
5. 添加通知发送历史查询
