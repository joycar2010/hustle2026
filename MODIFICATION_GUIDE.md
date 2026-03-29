# UserManagement.vue 修改指南

## 第一步：导入密码输入组件

在 `<script setup>` 部分添加导入：

```javascript
import PasswordInput from '@/components/PasswordInput.vue'
```

## 第二步：修复表单自动填充

### 2.1 新增用户模态框 - 邮箱字段（行502）
```html
<!-- 修改前 -->
<input v-model="userForm.email" type="email"
  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
  placeholder="输入邮箱（可选）" />

<!-- 修改后 -->
<input v-model="userForm.email" type="email" autocomplete="off"
  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
  placeholder="输入邮箱（可选）" />
```

### 2.2 新增/编辑用户模态框 - 密码字段（行510-512）
```html
<!-- 修改前 -->
<input v-model="userForm.password" type="password" :required="!isEditUser"
  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
  placeholder="至少8个字符" />

<!-- 修改后 -->
<PasswordInput
  v-model="userForm.password"
  :required="!isEditUser"
  placeholder="至少8个字符"
  autocomplete="new-password"
/>
```

### 2.3 编辑用户 - 飞书 Open ID（行537-539）
已经有 `autocomplete="off"`，保持不变。

### 2.4 编辑账户模态框 - API Secret（行660）
```html
<!-- 修改前 -->
<input v-model="accountForm.api_secret" type="password" :required="!isEditAccount" autocomplete="new-password"
  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
  placeholder="留空表示不修改" />

<!-- 修改后 -->
<PasswordInput
  v-model="accountForm.api_secret"
  :required="!isEditAccount"
  placeholder="留空表示不修改"
  autocomplete="new-password"
/>
```

### 2.5 编辑账户模态框 - Passphrase（行666）
```html
<!-- 修改前 -->
<input v-model="accountForm.passphrase" type="password"
  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
  placeholder="留空表示不修改" />

<!-- 修改后 -->
<PasswordInput
  v-model="accountForm.passphrase"
  :required="false"
  placeholder="留空表示不修改"
  autocomplete="new-password"
/>
```

### 2.6 MT5 客户端 - MT5 密码（行726-728）
```html
<!-- 修改前 -->
<input v-model="mt5Form.mt5_password" type="password" :required="!isEditMT5"
  autocomplete="new-password"
  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
  placeholder="留空表示不修改" />

<!-- 修改后 -->
<PasswordInput
  v-model="mt5Form.mt5_password"
  :required="!isEditMT5"
  placeholder="留空表示不修改"
  autocomplete="new-password"
/>
```

## 第三步：修改 MT5 管理标签名称

### 3.1 修改标签定义（行953-957）
```javascript
// 修改前
const tabs = [
  { id: 'users',    label: '用户账号' },
  { id: 'accounts', label: '绑定账户' },
  { id: 'mt5',      label: 'MT5管理' },
]

// 修改后
const tabs = [
  { id: 'users',    label: '用户账号' },
  { id: 'accounts', label: '绑定账户' },
  { id: 'mt5',      label: 'MT5账户管理' },
]
```

### 3.2 修改子标签（找到 mt5SubTab 相关的 UI 部分）
将 "客户端连接" 改为 "MT5账户管理"
将 "服务实例" 保留或整合到同一页面

## 第四步：MT5 账户卡片修改

### 4.1 添加"部署客户端"按钮
在 MT5 客户端卡片中添加新按钮：

```html
<button @click="openDeployForClient(client)"
  class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors">
  部署客户端
</button>
```

### 4.2 添加连接状态显示
```html
<div v-if="client.is_connected" class="flex items-center gap-1 text-[#0ecb81] text-xs">
  <span class="w-2 h-2 rounded-full bg-[#0ecb81] animate-pulse"></span>
  <span>连接中</span>
</div>
```

### 4.3 禁用删除按钮逻辑
```javascript
function canDeleteClient(client) {
  return !client.is_active && !client.is_connected
}
```

```html
<button @click="deleteMT5Client(client)"
  :disabled="!canDeleteClient(client)"
  :class="[
    'px-2 py-1 rounded text-xs transition-colors',
    canDeleteClient(client)
      ? 'bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20'
      : 'bg-gray-600/20 text-gray-500 cursor-not-allowed'
  ]">
  删除
</button>
```

## 第五步：后端数据库修改

### 5.1 修改 mt5_instances 表
```sql
ALTER TABLE mt5_instances ADD COLUMN client_id UUID REFERENCES mt5_clients(client_id);
ALTER TABLE mt5_instances ADD COLUMN instance_type VARCHAR(20) DEFAULT 'primary';
ALTER TABLE mt5_instances ADD CONSTRAINT check_instance_type CHECK (instance_type IN ('primary', 'backup'));
```

### 5.2 添加唯一约束
```sql
-- 确保一个账户最多2个实例
CREATE UNIQUE INDEX idx_mt5_instances_client_type ON mt5_instances(client_id, instance_type);
```

### 5.3 添加 is_connected 字段到 mt5_clients
```sql
ALTER TABLE mt5_clients ADD COLUMN is_connected BOOLEAN DEFAULT FALSE;
```

## 第六步：后端 API 修改

### 6.1 创建新的 API 端点

在 `backend/app/api/v1/mt5_clients.py` 中添加：

```python
@router.post("/{client_id}/deploy-instance")
async def deploy_instance_for_client(
    client_id: UUID,
    instance_data: MT5InstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """为 MT5 账户部署新实例"""
    # 检查账户是否存在
    client = await db.get(MT5Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="MT5 account not found")

    # 检查实例数量（最多2个）
    result = await db.execute(
        select(func.count()).where(MT5Instance.client_id == client_id)
    )
    count = result.scalar()
    if count >= 2:
        raise HTTPException(status_code=400, detail="Maximum 2 instances per account")

    # 创建实例...
```

### 6.2 添加主备切换 API
```python
@router.post("/{client_id}/switch-instance")
async def switch_active_instance(
    client_id: UUID,
    target_instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """切换活动实例"""
    # 停用当前活动实例
    # 启用目标实例
    # 更新连接状态
```

## 实施顺序建议

1. **第一阶段**（简单，立即可做）：
   - 创建 PasswordInput 组件 ✓
   - 修复表单自动填充
   - 添加密码显示/隐藏功能

2. **第二阶段**（中等难度）：
   - 修改数据库结构
   - 创建后端 API

3. **第三阶段**（复杂）：
   - 重构前端 MT5 管理页面
   - 实现主备切换逻辑
   - 添加连接状态检查

## 注意事项

1. **数据迁移**：现有 MT5 实例需要关联到对应的 MT5 账户
2. **向后兼容**：确保现有功能不受影响
3. **测试**：每个阶段完成后进行充分测试
4. **备份**：修改前备份数据库和代码
