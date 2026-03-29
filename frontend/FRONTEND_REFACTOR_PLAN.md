# 前端 MT5 管理页面重构方案

## 新的页面结构

```
MT5账户管理
├── 用户选择器
├── MT5账户选择器
└── MT5账户卡片列表
    ├── MT5账户卡片
    │   ├── 账户信息（登录号、服务器）
    │   ├── 连接状态指示器
    │   ├── 启用/停用开关
    │   ├── 操作按钮
    │   │   ├── 部署客户端
    │   │   ├── 编辑
    │   │   └── 删除（连接中禁用）
    │   └── 服务实例列表（展开/折叠）
    │       ├── 主跑实例卡片
    │       │   ├── 实例信息
    │       │   ├── 状态指示
    │       │   ├── 启用标记
    │       │   └── 操作按钮（刷新、启动、停止、重启、编辑、删除）
    │       └── 备用实例卡片
    │           ├── 实例信息
    │           ├── 状态指示
    │           ├── 启用标记
    │           └── 操作按钮（刷新、启动、停止、重启、编辑、删除）
    └── 空状态提示
```

## 数据结构

```javascript
// MT5 客户端（账户）
{
  client_id: 1,
  client_name: "主账户",
  mt5_login: "3971962",
  mt5_server: "MetaQuotes-Demo",
  connection_status: "connected", // connected/disconnected/error
  is_active: true,
  instances: [
    {
      instance_id: "uuid",
      instance_name: "主跑实例",
      instance_type: "primary",
      server_ip: "54.249.66.53",
      service_port: 8003,
      status: "running", // running/stopped/error
      is_active: true
    },
    {
      instance_id: "uuid",
      instance_name: "备用实例",
      instance_type: "backup",
      server_ip: "54.249.66.53",
      service_port: 8004,
      status: "stopped",
      is_active: false
    }
  ]
}
```

## 关键功能实现

### 1. 加载数据

```javascript
async function loadMT5ClientsWithInstances() {
  if (!mt5SelectedAccountId.value) return

  mt5Loading.value = true
  try {
    // 加载客户端列表
    const clientsRes = await api.get(`/api/v1/mt5/clients?account_id=${mt5SelectedAccountId.value}`)
    const clients = clientsRes.data || []

    // 为每个客户端加载实例
    for (const client of clients) {
      const instancesRes = await api.get(`/api/v1/mt5/instances/client/${client.client_id}`)
      client.instances = instancesRes.data || []
    }

    mt5Clients.value = clients
  } catch (e) {
    apiErr('加载MT5账户失败', e)
  } finally {
    mt5Loading.value = false
  }
}
```

### 2. 部署客户端

```javascript
async function openDeployForClient(client) {
  deployingClient.value = client

  // 检查已有实例数量
  const instanceCount = client.instances?.length || 0
  if (instanceCount >= 2) {
    toast('该账户已有2个实例（主跑+备用），无法继续添加', 'error')
    return
  }

  // 确定实例类型
  const hasPrimary = client.instances?.some(i => i.instance_type === 'primary')
  deployForm.value.instance_type = hasPrimary ? 'backup' : 'primary'
  deployForm.value.instance_name = hasPrimary ? '备用实例' : '主跑实例'

  // 自动填充MT5信息
  deployForm.value.mt5_login = client.mt5_login
  deployForm.value.mt5_server = client.mt5_server

  showDeployModal.value = true
}

async function deployInstance() {
  deploying.value = true
  try {
    await api.post(`/api/v1/mt5/instances/client/${deployingClient.value.client_id}/deploy`, deployForm.value)
    toast('实例部署成功')
    showDeployModal.value = false
    await loadMT5ClientsWithInstances()
  } catch (e) {
    apiErr('部署失败', e)
  } finally {
    deploying.value = false
  }
}
```

### 3. 主备切换

```javascript
async function switchToInstance(client, instance) {
  if (instance.is_active) {
    toast('该实例已经是活动状态', 'info')
    return
  }

  if (!confirm(`确定要切换到${instance.instance_name}吗？\n当前活动实例将被停止。`)) {
    return
  }

  try {
    await api.post(`/api/v1/mt5/instances/client/${client.client_id}/switch`, {
      target_instance_id: instance.instance_id
    })
    toast('切换成功')
    await loadMT5ClientsWithInstances()
  } catch (e) {
    apiErr('切换失败', e)
  }
}
```

### 4. 删除保护

```javascript
function canDeleteClient(client) {
  // 连接中或启用状态不能删除
  return !client.is_active && client.connection_status !== 'connected'
}

function canDeleteInstance(instance) {
  // 活动实例不能删除
  return !instance.is_active
}

async function deleteMT5Client(client) {
  if (!canDeleteClient(client)) {
    toast('无法删除：账户处于连接或启用状态', 'error')
    return
  }

  if (client.instances?.length > 0) {
    toast('请先删除该账户下的所有实例', 'error')
    return
  }

  if (!confirm(`确定要删除MT5账户「${client.client_name}」吗？`)) {
    return
  }

  try {
    await api.delete(`/api/v1/mt5/clients/${client.client_id}`)
    toast('删除成功')
    await loadMT5ClientsWithInstances()
  } catch (e) {
    apiErr('删除失败', e)
  }
}
```

### 5. 健康检查

```javascript
async function checkClientHealth(client) {
  try {
    const res = await api.get(`/api/v1/mt5/instances/client/${client.client_id}/health`)
    const health = res.data

    // 更新客户端状态
    client.connection_status = health.overall_healthy ? 'connected' : 'disconnected'

    // 更新实例状态
    for (const instanceHealth of health.instances) {
      const instance = client.instances.find(i => i.instance_id === instanceHealth.instance_id)
      if (instance) {
        instance.status = instanceHealth.status
      }
    }

    toast('健康检查完成')
  } catch (e) {
    apiErr('健康检查失败', e)
  }
}
```

## UI 组件样式

### MT5账户卡片

```html
<div class="bg-dark-100 rounded-xl border border-border-primary p-4">
  <!-- 头部：账户信息 + 连接状态 -->
  <div class="flex items-start justify-between mb-3">
    <div class="flex-1">
      <div class="flex items-center gap-2 mb-1">
        <h3 class="font-semibold">{{ client.client_name }}</h3>
        <!-- 连接状态指示器 -->
        <div v-if="client.connection_status === 'connected'"
          class="flex items-center gap-1 text-[#0ecb81] text-xs">
          <span class="w-2 h-2 rounded-full bg-[#0ecb81] animate-pulse"></span>
          <span>连接中</span>
        </div>
      </div>
      <div class="text-xs text-text-tertiary space-y-0.5">
        <div>登录号：{{ client.mt5_login }}</div>
        <div>服务器：{{ client.mt5_server }}</div>
      </div>
    </div>

    <!-- 启用开关 -->
    <div class="flex items-center gap-2">
      <span class="text-xs text-text-tertiary">启用</span>
      <div @click="toggleClientActive(client)"
        :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
          client.is_active ? 'bg-[#0ecb81]' : 'bg-gray-600',
          client.connection_status === 'connected' ? 'opacity-50 cursor-not-allowed' : '']">
        <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
          client.is_active ? 'translate-x-4' : 'translate-x-0.5']"/>
      </div>
    </div>
  </div>

  <!-- 操作按钮 -->
  <div class="flex gap-2 mb-3">
    <button @click="openDeployForClient(client)"
      :disabled="(client.instances?.length || 0) >= 2"
      class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors disabled:opacity-40">
      部署客户端
    </button>
    <button @click="checkClientHealth(client)"
      class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
      健康检查
    </button>
    <button @click="openEditMT5(client)"
      class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
      编辑
    </button>
    <button @click="deleteMT5Client(client)"
      :disabled="!canDeleteClient(client)"
      :class="['px-3 py-1.5 rounded-lg text-xs transition-colors',
        canDeleteClient(client)
          ? 'bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20'
          : 'bg-gray-600/20 text-gray-500 cursor-not-allowed']">
      删除
    </button>
  </div>

  <!-- 服务实例列表 -->
  <div v-if="client.instances?.length > 0" class="border-t border-border-secondary pt-3">
    <div class="text-xs text-text-tertiary mb-2">服务实例</div>
    <div class="space-y-2">
      <InstanceCard
        v-for="instance in client.instances"
        :key="instance.instance_id"
        :instance="instance"
        :client="client"
        @switch="switchToInstance(client, instance)"
        @refresh="refreshInstanceStatus(instance)"
        @control="controlInstance(instance, $event)"
        @edit="openEditInstance(instance)"
        @delete="deleteInstance(instance)"
      />
    </div>
  </div>
</div>
```

### 实例卡片组件

```html
<div :class="['bg-dark-200 rounded-lg border p-3',
  instance.is_active ? 'border-primary' : 'border-border-primary']">
  <div class="flex items-start justify-between">
    <div class="flex-1">
      <div class="flex items-center gap-2 mb-1">
        <span class="text-sm font-medium">{{ instance.instance_name }}</span>
        <span :class="['px-1.5 py-0.5 rounded text-xs',
          instance.instance_type === 'primary'
            ? 'bg-primary/10 text-primary'
            : 'bg-[#f0b90b]/10 text-[#f0b90b]']">
          {{ instance.instance_type === 'primary' ? '主跑' : '备用' }}
        </span>
        <span v-if="instance.is_active"
          class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/10 text-[#0ecb81]">
          活动
        </span>
      </div>
      <div class="text-xs text-text-tertiary space-y-0.5">
        <div>端口：{{ instance.service_port }}</div>
        <div>状态：
          <span :class="getStatusClass(instance.status)">
            {{ getStatusText(instance.status) }}
          </span>
        </div>
      </div>
    </div>
  </div>

  <!-- 操作按钮 -->
  <div class="flex gap-1 mt-2 flex-wrap">
    <button v-if="!instance.is_active" @click="$emit('switch')"
      class="px-2 py-1 bg-primary/10 text-primary hover:bg-primary/20 rounded text-xs transition-colors">
      切换为活动
    </button>
    <button @click="$emit('refresh')"
      class="px-2 py-1 bg-dark-100 hover:bg-dark-50 text-text-secondary rounded text-xs transition-colors">
      刷新
    </button>
    <button v-if="instance.status !== 'running'" @click="$emit('control', 'start')"
      class="px-2 py-1 bg-[#0ecb81]/10 text-[#0ecb81] hover:bg-[#0ecb81]/20 rounded text-xs transition-colors">
      启动
    </button>
    <button v-if="instance.status === 'running'" @click="$emit('control', 'stop')"
      class="px-2 py-1 bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20 rounded text-xs transition-colors">
      停止
    </button>
    <button @click="$emit('control', 'restart')"
      class="px-2 py-1 bg-[#f0b90b]/10 text-[#f0b90b] hover:bg-[#f0b90b]/20 rounded text-xs transition-colors">
      重启
    </button>
    <button @click="$emit('edit')"
      class="px-2 py-1 bg-dark-100 hover:bg-dark-50 text-text-secondary rounded text-xs transition-colors">
      编辑
    </button>
    <button @click="$emit('delete')"
      :disabled="instance.is_active"
      :class="['px-2 py-1 rounded text-xs transition-colors',
        instance.is_active
          ? 'bg-gray-600/20 text-gray-500 cursor-not-allowed'
          : 'bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20']">
      删除
    </button>
  </div>
</div>
```

## 实施步骤

1. 修改数据加载逻辑，同时获取客户端和实例
2. 创建实例卡片子组件
3. 修改MT5账户卡片，添加实例列表展示
4. 实现部署客户端功能
5. 实现主备切换功能
6. 实现删除保护逻辑
7. 添加健康检查功能
8. 优化UI和交互体验
