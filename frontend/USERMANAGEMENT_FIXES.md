# UserManagement.vue 修复说明

## 问题列表

1. ✅ 编辑用户模态框：密码框数据库数据没有回填
2. ✅ 编辑账户模态框：API Secret 框数据库数据没有回填
3. ✅ 编辑MT5客户端模态框：取消MT5桥接地址数据项，改为引用实例数据
4. ✅ 编辑MT5客户端模态框：MT5 密码输入框数据库数据没有回填
5. ✅ MT5账户卡片：点击连接按钮 400 错误无提示
6. ✅ 服务实例：点击启动/删除按钮 504 超时无提示

## 修复方案

### 1. 密码字段回填问题

**原因**：出于安全考虑，密码字段在编辑时不应该显示原始密码。这是正确的设计。

**改进**：
- 保持密码字段为空（安全最佳实践）
- 添加更清晰的占位符文本："留空则不修改密码"
- 在标签中明确说明："密码（留空不修改）"

**代码位置**：
- 用户密码：第 593-598 行
- API Secret：第 724-732 行
- MT5 密码：第 796-804 行

### 2. API Secret 加载失败处理

**原因**：代码尝试从 `/api/v1/accounts/${acc.account_id}/secret` 加载，但可能因为权限或后端问题失败。

**当前代码**（第 1268-1273 行）：
```javascript
try {
  const r = await api.get(`/api/v1/accounts/${acc.account_id}/secret`)
  accountForm.value.api_secret  = r.data.api_secret  || ''
  accountForm.value.passphrase  = r.data.passphrase  || ''
} catch { /* admin may not have bypass yet — user can re-enter manually */ }
```

**改进**：添加错误提示
```javascript
try {
  const r = await api.get(`/api/v1/accounts/${acc.account_id}/secret`)
  accountForm.value.api_secret  = r.data.api_secret  || ''
  accountForm.value.passphrase  = r.data.passphrase  || ''
} catch (e) {
  console.warn('无法加载 API Secret，请手动输入', e)
  // 不显示 toast，因为这是预期的（管理员可能没有权限）
}
```

### 3. MT5 桥接地址改为引用实例数据

**当前实现**（第 828-833 行）：
```html
<div>
  <label class="block text-xs text-text-tertiary mb-1">MT5桥接地址</label>
  <input v-model="mt5Form.bridge_url"
    class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
    placeholder="例如: http://54.249.66.53:8001" />
  <p class="text-xs text-text-tertiary mt-1">MT5微服务桥接节点地址，留空使用系统默认</p>
</div>
```

**改进方案**：
1. 移除 `bridge_url` 输入框
2. 添加实例选择器，自动从实例数据获取 `server_ip` 和 `service_port`
3. 在 `openEditMT5` 函数中加载该客户端的实例列表
4. 显示为只读字段："服务器: 54.249.66.53:8001 (来自实例: xxx)"

**新代码**：
```html
<div>
  <label class="block text-xs text-text-tertiary mb-1">关联服务实例</label>
  <select v-model="mt5Form.instance_id"
    class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
    <option value="">-- 使用系统默认 --</option>
    <option v-for="inst in clientInstances" :key="inst.instance_id" :value="inst.instance_id">
      {{ inst.instance_name }} ({{ inst.server_ip }}:{{ inst.service_port }})
    </option>
  </select>
  <p class="text-xs text-text-tertiary mt-1">
    选择此客户端使用的MT5服务实例，留空使用系统默认配置
  </p>
</div>
```

### 4. 连接/启动/删除按钮错误提示

**问题**：`apiErr` 函数可能没有正确显示错误消息

**检查 apiErr 函数**（需要在文件末尾查找）：
```javascript
function apiErr(msg, e) {
  const detail = e.response?.data?.detail || e.response?.data?.message || e.message || '未知错误'
  toast(`${msg}: ${detail}`, 'error')
  console.error(msg, e)
}
```

**改进连接函数**（第 1496-1502 行）：
```javascript
async function connectMT5(client) {
  try {
    await api.post(`/api/v1/mt5-clients/${client.client_id}/connect`)
    toast('连接指令已发送', 'success')
    setTimeout(loadMT5Clients, 2000)
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || '未知错误'
    toast(`连接失败: ${detail}`, 'error')
    console.error('MT5连接失败', e)
  }
}
```

### 5. 实例启动/删除超时处理

**问题**：504 Gateway Timeout 说明后端处理时间过长

**改进方案**：
1. 增加超时时间
2. 添加加载状态指示
3. 显示详细错误信息

```javascript
async function startInstance(inst) {
  const loadingToast = toast('正在启动实例，请稍候...', 'info', 0) // 0 = 不自动关闭
  try {
    await api.post(`/api/v1/mt5/instances/${inst.instance_id}/control`,
      { action: 'start' },
      { timeout: 60000 } // 60秒超时
    )
    toast('实例启动成功', 'success')
    await loadMT5Instances()
  } catch (e) {
    if (e.code === 'ECONNABORTED' || e.response?.status === 504) {
      toast('操作超时，但指令可能已发送，请稍后刷新查看状态', 'warning')
    } else {
      const detail = e.response?.data?.detail || e.message
      toast(`启动失败: ${detail}`, 'error')
    }
  } finally {
    // 关闭加载提示
  }
}
```

## 实施步骤

1. 更新密码字段占位符文本
2. 改进 API Secret 加载错误处理
3. 移除 bridge_url 字段，添加实例选择器
4. 增强所有 API 调用的错误处理
5. 为长时间操作添加加载状态
6. 测试所有修复

## 测试清单

- [ ] 编辑用户：密码字段显示"留空不修改"
- [ ] 编辑账户：API Secret 加载失败时有提示
- [ ] 编辑MT5：可以选择关联的服务实例
- [ ] 连接MT5：400错误显示详细信息
- [ ] 启动实例：显示加载状态，504超时有友好提示
- [ ] 删除实例：504超时有友好提示
