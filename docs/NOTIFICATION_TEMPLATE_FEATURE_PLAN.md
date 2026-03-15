# 通知模板管理 - 自动检查和冷却时间功能实现计划

## 需求
在通知模板管理中为每个模板添加：
1. 自动检查开关 - 控制是否启用自动检查触发
2. 冷却时间设置 - 自定义每个模板的冷却时间

## 当前状态
- ✅ 数据库已有 `cooldown_seconds` 字段
- ✅ 后端API已支持 `cooldown_seconds` 更新
- ❌ 缺少 `auto_check_enabled` 字段
- ❌ 前端未实现编辑界面

## 实现步骤

### 1. 数据库修改
添加 `auto_check_enabled` 字段到 `notification_templates` 表

```sql
ALTER TABLE notification_templates
ADD COLUMN auto_check_enabled BOOLEAN DEFAULT true;

COMMENT ON COLUMN notification_templates.auto_check_enabled IS '是否启用自动检查触发';
```

### 2. 后端修改

#### 2.1 更新模型 (app/models/notification_config.py)
```python
class NotificationTemplate(Base):
    # ... 现有字段 ...
    auto_check_enabled = Column(Boolean, default=True, nullable=False)
```

#### 2.2 更新API模型 (app/api/v1/notifications.py)
```python
class NotificationTemplateUpdate(BaseModel):
    # ... 现有字段 ...
    auto_check_enabled: Optional[bool] = None
    cooldown_seconds: Optional[int] = None  # 已存在
```

#### 2.3 更新风险检查逻辑 (app/tasks/broadcast_tasks.py)
在检查点差提醒前，先检查模板的 `auto_check_enabled` 状态

### 3. 前端修改

#### 3.1 查找通知模板管理页面
位置：`frontend/src/views/System.vue` 或相关组件

#### 3.2 添加编辑字段
在模板编辑对话框中添加：
- 自动检查开关 (el-switch)
- 冷却时间输入 (el-input-number)

```vue
<el-form-item label="自动检查">
  <el-switch
    v-model="templateForm.auto_check_enabled"
    active-text="启用"
    inactive-text="禁用"
  />
</el-form-item>

<el-form-item label="冷却时间">
  <el-input-number
    v-model="templateForm.cooldown_seconds"
    :min="0"
    :max="3600"
    :step="60"
  />
  <span class="ml-2">秒</span>
</el-form-item>
```

## 注意事项

1. **向后兼容**: 新字段默认值应该保持现有行为
2. **权限控制**: 只有管理员可以修改这些设置
3. **验证**: 冷却时间应该有合理的范围限制（如0-3600秒）
4. **文档**: 需要在界面上说明这些字段的作用

## 测试计划

1. 数据库迁移测试
2. API更新测试
3. 前端界面测试
4. 自动检查逻辑测试
5. 冷却时间功能测试

## 优先级

由于当前系统已经在使用全局的 `SPREAD_ALERT_COOLDOWN` 配置（300秒），
建议先实现前端界面，让用户可以查看和编辑这些值，
然后再逐步将逻辑从全局配置迁移到每个模板的独立配置。
