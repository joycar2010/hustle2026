<template>
  <div class="container mx-auto px-4 py-6 space-y-5">

    <!-- 页头 -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h1 class="text-2xl font-bold">用户管理</h1>
        <p class="text-xs text-text-tertiary mt-0.5">用户账号 · 绑定账户 · MT5客户端 · Go 后端</p>
      </div>
    </div>

    <!-- 子 Tab -->
    <div class="flex gap-1 border-b border-border-primary">
      <button v-for="t in tabs" :key="t.id" @click="activeTab = t.id"
        :class="['px-4 py-2 text-sm font-medium transition-colors relative whitespace-nowrap',
          activeTab === t.id ? 'text-primary' : 'text-text-secondary hover:text-text-primary']">
        {{ t.label }}
        <div v-if="activeTab === t.id" class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"></div>
      </button>
    </div>

    <!-- ═══════════════════════════════════════════
         Tab 1: 用户账号
    ═══════════════════════════════════════════ -->
    <div v-if="activeTab === 'users'" class="space-y-4">
      <!-- 统计卡片 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
          <div class="text-xs text-text-tertiary mb-1">总用户数</div>
          <div class="text-xl font-bold font-mono text-text-primary">{{ users.length }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
          <div class="text-xs text-text-tertiary mb-1">启用用户</div>
          <div class="text-xl font-bold font-mono text-[#0ecb81]">{{ users.filter(u => u.is_active).length }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
          <div class="text-xs text-text-tertiary mb-1">禁用用户</div>
          <div class="text-xl font-bold font-mono text-[#f6465d]">{{ users.filter(u => !u.is_active).length }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
          <div class="text-xs text-text-tertiary mb-1">管理员</div>
          <div class="text-xl font-bold font-mono text-[#f0b90b]">{{ adminCount }}</div>
        </div>
      </div>

      <!-- 用户表格 -->
      <div class="bg-dark-100 rounded-2xl border border-border-primary overflow-hidden">
        <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between flex-wrap gap-2">
          <span class="font-semibold text-sm">用户列表</span>
          <div class="flex gap-2">
            <button @click="loadUsers"
              class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
              刷新
            </button>
            <button @click="openAddUser"
              class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors">
              + 新增用户
            </button>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs">
            <thead>
              <tr class="border-b border-border-secondary text-text-tertiary">
                <th class="text-left px-4 py-2.5">用户名</th>
                <th class="text-left px-3 py-2.5">邮箱</th>
                <th class="text-left px-3 py-2.5">RBAC角色</th>
                <th class="text-center px-3 py-2.5">状态</th>
                <th class="text-left px-3 py-2.5">创建时间</th>
                <th class="text-center px-4 py-2.5">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="usersLoading">
                <td colspan="6" class="text-center py-10 text-text-tertiary">加载中...</td>
              </tr>
              <tr v-else-if="!users.length">
                <td colspan="6" class="text-center py-10 text-text-tertiary">暂无用户数据</td>
              </tr>
              <tr v-for="u in users" :key="u.user_id"
                class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="px-4 py-2.5 font-medium">{{ u.username }}</td>
                <td class="px-3 py-2.5 text-text-tertiary">{{ u.email || '-' }}</td>
                <td class="px-3 py-2.5">
                  <div class="flex flex-wrap gap-1">
                    <span v-for="r in (u.rbac_roles || [])" :key="r.role_id || r"
                      class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/10 text-[#0ecb81]">
                      {{ r.role_name || r }}
                    </span>
                    <span v-if="!u.rbac_roles?.length" class="text-text-tertiary">未分配</span>
                  </div>
                </td>
                <td class="px-3 py-2.5 text-center">
                  <span :class="u.is_active
                    ? 'bg-[#0ecb81]/10 text-[#0ecb81] px-1.5 py-0.5 rounded'
                    : 'bg-[#f6465d]/10 text-[#f6465d] px-1.5 py-0.5 rounded'">
                    {{ u.is_active ? '启用' : '禁用' }}
                  </span>
                </td>
                <td class="px-3 py-2.5 text-text-tertiary font-mono">{{ fmtDate(u.create_time) }}</td>
                <td class="px-4 py-2.5 text-center">
                  <div class="flex items-center justify-center gap-2">
                    <button @click="openEditUser(u)"
                      class="text-primary hover:text-primary-hover text-xs transition-colors">编辑</button>
                    <button @click="openAssignRole(u)"
                      class="text-[#0ecb81] hover:opacity-80 text-xs transition-colors">分配角色</button>
                    <button @click="toggleUserStatus(u)"
                      :class="u.is_active ? 'text-[#f0b90b]' : 'text-[#0ecb81]'"
                      class="hover:opacity-80 text-xs transition-colors">
                      {{ u.is_active ? '禁用' : '启用' }}
                    </button>
                    <button @click="deleteUser(u)"
                      class="text-[#f6465d] hover:opacity-80 text-xs transition-colors">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════
         Tab 2: 绑定账户
    ═══════════════════════════════════════════ -->
    <div v-if="activeTab === 'accounts'" class="space-y-4">
      <!-- 用户选择器 + 工具栏 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3 flex items-center gap-3 flex-wrap">
        <span class="text-sm text-text-tertiary whitespace-nowrap">选择用户：</span>
        <select v-model="selectedAccountUserId" @change="loadUserAccounts"
          class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary min-w-[180px]">
          <option value="">-- 全部用户 --</option>
          <option v-for="u in users" :key="u.user_id" :value="u.user_id">
            {{ u.username }} ({{ u.rbac_roles?.[0]?.role_name || u.role || '未分配' }})
          </option>
        </select>
        <button @click="loadUserAccounts"
          class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
          刷新
        </button>
        <button @click="openAddAccount"
          class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors">
          + 新增账户
        </button>
        <span class="text-xs text-text-tertiary ml-auto">共 {{ accounts.length }} 个账户</span>
      </div>

      <!-- 账户卡片列表 -->
      <div v-if="accountsLoading" class="text-center py-12 text-text-tertiary text-sm">加载中...</div>
      <div v-else-if="!accounts.length" class="text-center py-12 text-text-tertiary text-sm">暂无账户数据</div>
      <div v-else class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        <div v-for="acc in accounts" :key="acc.account_id"
          class="bg-dark-100 rounded-2xl border border-border-primary p-4 space-y-3 transition-all"
          :class="!acc.is_active ? 'opacity-60' : ''">

          <!-- 账户头 -->
          <div class="flex items-start justify-between">
            <div class="flex-1 min-w-0">
              <div class="font-bold text-sm truncate">{{ acc.account_name }}</div>
              <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                <span class="text-xs text-text-tertiary font-mono">ID: {{ acc.account_id }}</span>
                <span class="px-1.5 py-0.5 rounded text-xs bg-blue-500/10 text-blue-400">
                  {{ getPlatformName(acc.platform_id, acc.is_mt5_account) }}
                </span>
                <span v-if="acc.is_default" class="px-1.5 py-0.5 rounded text-xs bg-[#f0b90b]/10 text-[#f0b90b]">默认</span>
                <span v-if="!acc.is_active" class="px-1.5 py-0.5 rounded text-xs bg-dark-200 text-text-tertiary">禁用</span>
              </div>
              <div v-if="acc._username" class="mt-1 text-xs text-text-tertiary">
                所属用户：<span class="text-text-secondary">{{ acc._username }}</span>
              </div>
            </div>
            <!-- 启用/禁用开关 -->
            <div @click="toggleAccount(acc)"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors flex-shrink-0 ml-2',
                acc.is_active ? 'bg-[#0ecb81]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                acc.is_active ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
          </div>

          <!-- API 信息 -->
          <div class="bg-dark-200 rounded-lg p-2.5 text-xs space-y-1.5">
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary">API Key:</span>
              <span class="font-mono">{{ maskStr(acc.api_key) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary">API Secret:</span>
              <span class="font-mono text-text-tertiary">{{ maskSecret(acc.api_secret) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary">杠杆倍数:</span>
              <span class="font-mono">{{ acc.leverage || '-' }}x</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary">创建时间:</span>
              <span class="font-mono text-text-tertiary">{{ fmtDate(acc.create_time) }}</span>
            </div>
          </div>

          <!-- IPIPGO 静态IP代理配置 -->
          <div class="bg-dark-200 rounded-lg p-2.5 text-xs">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-text-tertiary font-medium">IPIPGO 静态IP</span>
              <button @click="openProxyConfig(acc)"
                class="px-1.5 py-0.5 bg-dark-50 hover:bg-dark-100 border border-border-primary rounded text-text-secondary transition-colors">
                {{ acc.proxy_config ? '编辑' : '配置' }}
              </button>
            </div>
            <div v-if="acc.proxy_config" class="space-y-1">
              <div class="flex justify-between items-center">
                <span class="text-text-tertiary">IP地址:</span>
                <span class="font-mono text-text-secondary">{{ acc.proxy_config.host || '--' }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-text-tertiary">端口:</span>
                <span class="font-mono text-text-secondary">{{ acc.proxy_config.port || '--' }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-text-tertiary">类型:</span>
                <span class="font-mono text-text-secondary uppercase">{{ acc.proxy_config.proxy_type || 'socks5' }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-text-tertiary">认证:</span>
                <span :class="acc.proxy_config.username ? 'text-green-400' : 'text-text-tertiary'">
                  {{ acc.proxy_config.username ? '已配置' : '无' }}
                </span>
              </div>
            </div>
            <div v-else class="text-center text-text-tertiary py-1">未配置代理 — 使用服务器直连</div>
          </div>

          <!-- 操作按钮 -->
          <div class="flex gap-2">
            <button @click="openEditAccount(acc)"
              class="flex-1 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
              编辑
            </button>
            <button @click="deleteAccount(acc)"
              class="flex-1 py-1.5 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded-lg text-xs border border-[#f6465d]/20 transition-colors">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════
         Tab 3: MT5客户端 & 实例管理
    ═══════════════════════════════════════════ -->
    <div v-if="activeTab === 'mt5'" class="space-y-4">
      <!-- 子导航：客户端连接 vs 服务实例 -->
      <div class="flex gap-2 bg-dark-100 rounded-xl border border-border-primary p-1">
        <button @click="mt5SubTab = 'clients'"
          :class="['flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors',
            mt5SubTab === 'clients' ? 'bg-primary text-dark-300' : 'text-text-secondary hover:text-text-primary']">
          客户端连接
        </button>
        <button @click="mt5SubTab = 'instances'"
          :class="['flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors',
            mt5SubTab === 'instances' ? 'bg-primary text-dark-300' : 'text-text-secondary hover:text-text-primary']">
          服务实例
        </button>
      </div>
      <!-- ═══ 客户端连接子页面 ═══ -->
      <div v-if="mt5SubTab === 'clients'" class="space-y-4">
        <!-- 选择器工具栏 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3 flex items-center gap-3 flex-wrap">
          <span class="text-sm text-text-tertiary whitespace-nowrap">选择用户：</span>
          <select v-model="mt5SelectedUserId" @change="onMt5UserChange"
            class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary min-w-[160px]">
            <option value="">-- 选择用户 --</option>
            <option v-for="u in users" :key="u.user_id" :value="u.user_id">{{ u.username }}</option>
          </select>
          <span class="text-sm text-text-tertiary whitespace-nowrap">选择账户：</span>
          <select v-model="mt5SelectedAccountId" @change="loadMT5Clients"
            :disabled="!mt5SelectedUserId"
            class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary min-w-[200px] disabled:opacity-40">
            <option value="">-- 选择MT5账户 --</option>
            <option v-for="acc in mt5Accounts" :key="acc.account_id" :value="acc.account_id">
              {{ acc.account_name }} (ID: {{ acc.account_id }})
            </option>
          </select>
          <button @click="loadMT5Clients" :disabled="!mt5SelectedAccountId"
            class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors disabled:opacity-40">
            刷新
          </button>
          <button @click="openAddMT5" :disabled="!mt5SelectedAccountId"
            class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors disabled:opacity-40">
            + 新增客户端
          </button>
        </div>

      <!-- 提示状态 -->
      <div v-if="!mt5SelectedAccountId" class="text-center py-12 text-text-tertiary text-sm">
        请先选择用户和MT5账户
      </div>
      <div v-else-if="mt5Loading" class="text-center py-12 text-text-tertiary text-sm">加载中...</div>
      <div v-else-if="!mt5Clients.length" class="text-center py-12 text-text-tertiary text-sm">
        该账户暂无MT5客户端，点击「+ 新增客户端」添加
      </div>

        <!-- 客户端卡片 -->
        <div v-else class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        <div v-for="client in mt5Clients" :key="client.client_id"
          class="bg-dark-100 rounded-2xl border p-4 space-y-3 transition-all"
          :class="getMT5BorderColor(client)">

          <!-- 头部 -->
          <div class="flex items-start justify-between">
            <div class="flex-1 min-w-0">
              <div class="font-bold text-sm">{{ client.client_name }}</div>
              <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                <span class="px-1.5 py-0.5 rounded text-xs" :class="getMT5StatusClass(client.connection_status)">
                  {{ getMT5StatusText(client.connection_status) }}
                </span>
                <span v-if="!client.is_active"
                  class="px-1.5 py-0.5 rounded text-xs bg-dark-200 text-text-tertiary">未启用</span>
                <span class="text-xs text-text-tertiary">优先级: {{ client.priority }}</span>
              </div>
            </div>
            <!-- 启用开关 -->
            <div @click="toggleMT5Active(client)"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors flex-shrink-0 ml-2',
                client.is_active ? 'bg-[#0ecb81]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                client.is_active ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
          </div>

          <!-- 详情 -->
          <div class="text-xs space-y-1.5">
            <div class="flex justify-between">
              <span class="text-text-tertiary">MT5 登录:</span>
              <span class="font-mono">{{ client.mt5_login }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">服务器:</span>
              <span class="font-mono">{{ client.mt5_server }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">密码类型:</span>
              <span>{{ client.password_type === 'primary' ? '主密码' : '只读密码' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">路径:</span>
              <span class="font-mono text-xs truncate max-w-[180px]" :title="client.mt5_path">{{ client.mt5_path }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">代理:</span>
              <span>{{ client.proxy_id ? `ID: ${client.proxy_id}` : '直连' }}</span>
            </div>
          </div>

          <!-- 连接统计 -->
          <div v-if="client.total_connections > 0" class="bg-dark-200 rounded-lg p-2 text-xs space-y-1">
            <div class="flex justify-between">
              <span class="text-text-tertiary">连接次数:</span>
              <span>{{ client.total_connections }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">失败次数:</span>
              <span :class="client.failed_connections > 0 ? 'text-[#f6465d]' : ''">
                {{ client.failed_connections }}
              </span>
            </div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">平均延迟:</span>
              <span>{{ client.avg_latency_ms?.toFixed(0) || 0 }} ms</span>
            </div>
          </div>

          <!-- 操作 -->
          <div class="flex gap-2">
            <button v-if="client.connection_status !== 'connected'" @click="connectMT5(client)"
              class="flex-1 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary rounded-lg text-xs border border-primary/20 transition-colors">
              连接
            </button>
            <button v-else @click="disconnectMT5(client)"
              class="flex-1 py-1.5 bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] rounded-lg text-xs border border-[#f0b90b]/20 transition-colors">
              断开
            </button>
            <button @click="openEditMT5(client)"
              class="flex-1 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
              编辑
            </button>
            <button @click="deleteMT5(client)"
              class="flex-1 py-1.5 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded-lg text-xs border border-[#f6465d]/20 transition-colors">
              删除
            </button>
          </div>
        </div>
      </div>
      </div>

      <!-- ═══ 服务实例子页面 ═══ -->
      <div v-if="mt5SubTab === 'instances'" class="space-y-4">
        <!-- 工具栏 -->
        <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3 flex items-center justify-between flex-wrap gap-3">
          <span class="text-sm text-text-secondary">管理 Windows Server 上的 MT5 服务实例</span>
          <div class="flex gap-2">
            <button @click="loadMT5Instances"
              class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
              刷新
            </button>
            <button @click="openDeployInstance"
              class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs transition-colors">
              + 部署新实例
            </button>
          </div>
        </div>

        <!-- 实例列表 -->
        <div v-if="instancesLoading" class="text-center py-12 text-text-tertiary text-sm">加载中...</div>
        <div v-else-if="!mt5Instances.length" class="text-center py-12 text-text-tertiary text-sm">暂无实例，点击「部署新实例」开始</div>
        <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div v-for="inst in mt5Instances" :key="inst.instance_id"
            class="bg-dark-100 rounded-2xl border p-4 space-y-3"
            :class="getInstanceBorderColor(inst.status)">

            <!-- 实例头 -->
            <div class="flex items-start justify-between">
              <div class="flex-1 min-w-0">
                <div class="font-bold text-sm">{{ inst.instance_name }}</div>
                <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                  <span class="px-1.5 py-0.5 rounded text-xs" :class="getInstanceStatusClass(inst.status)">
                    {{ getInstanceStatusText(inst.status) }}
                  </span>
                  <span class="text-xs text-text-tertiary font-mono">{{ inst.server_ip }}:{{ inst.service_port }}</span>
                  <span v-if="inst.auto_start" class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/10 text-[#0ecb81]">自启</span>
                </div>
              </div>
            </div>

            <!-- 实例详情 -->
            <div class="bg-dark-200 rounded-lg p-2.5 text-xs space-y-1.5">
              <div class="flex justify-between">
                <span class="text-text-tertiary">MT5路径:</span>
                <span class="font-mono text-xs truncate max-w-[200px]" :title="inst.mt5_path">{{ inst.mt5_path }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-text-tertiary">部署路径:</span>
                <span class="font-mono text-xs truncate max-w-[200px]" :title="inst.deploy_path">{{ inst.deploy_path }}</span>
              </div>
              <div v-if="inst.mt5_data_path" class="flex justify-between">
                <span class="text-text-tertiary">数据目录:</span>
                <span class="font-mono text-xs truncate max-w-[200px]" :title="inst.mt5_data_path">{{ inst.mt5_data_path }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-text-tertiary">便携版:</span>
                <span>{{ inst.is_portable ? '是' : '否' }}</span>
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="flex gap-2">
              <button @click="controlInstance(inst, 'start')" :disabled="inst.status === 'running'"
                class="flex-1 py-1.5 bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] rounded-lg text-xs border border-[#0ecb81]/20 transition-colors disabled:opacity-40">
                启动
              </button>
              <button @click="controlInstance(inst, 'stop')" :disabled="inst.status === 'stopped'"
                class="flex-1 py-1.5 bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] rounded-lg text-xs border border-[#f0b90b]/20 transition-colors disabled:opacity-40">
                停止
              </button>
              <button @click="controlInstance(inst, 'restart')"
                class="flex-1 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary rounded-lg text-xs border border-primary/20 transition-colors">
                重启
              </button>
              <button @click="refreshInstanceStatus(inst)"
                class="py-1.5 px-3 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-xs border border-border-primary transition-colors">
                刷新
              </button>
              <button @click="deleteInstance(inst)"
                class="py-1.5 px-3 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded-lg text-xs border border-[#f6465d]/20 transition-colors">
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════════════════════════════════════
         Modal: 新增/编辑用户
    ════════════════════════════════════════ -->
    <div v-if="showUserModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      @click.self="showUserModal = false">
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">{{ isEditUser ? '编辑用户' : '新增用户' }}</h3>
          <button @click="showUserModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="saveUser" class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-text-tertiary mb-1">用户名 *</label>
            <input v-model="userForm.username" required :disabled="isEditUser"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary disabled:opacity-50"
              placeholder="输入用户名" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">邮箱</label>
            <input v-model="userForm.email" type="email"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="输入邮箱（可选）" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">
              {{ isEditUser ? '密码（留空表示不修改）' : '密码 *' }}
            </label>
            <input v-model="userForm.password" type="password" :required="!isEditUser"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="至少8个字符" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">角色</label>
            <select v-model="userForm.role"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="交易员">交易员</option>
              <option value="观察员">观察员</option>
              <option value="管理员">管理员</option>
            </select>
          </div>
          <div class="flex items-center gap-3">
            <div @click="userForm.is_active = !userForm.is_active"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                userForm.is_active ? 'bg-[#0ecb81]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                userForm.is_active ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">{{ userForm.is_active ? '启用账号' : '禁用账号' }}</span>
          </div>
          <!-- 飞书配置（仅编辑时显示） -->
          <div v-if="isEditUser" class="border-t border-border-secondary pt-3 space-y-3">
            <div class="text-xs font-semibold text-text-tertiary uppercase tracking-wide">飞书通知配置</div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">飞书 Open ID</label>
              <input v-model="userForm.feishu_open_id" type="text" autocomplete="off"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                placeholder="ou_xxxxxxxxxxxxxxxx（留空不修改）" />
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">飞书手机号</label>
              <input v-model="userForm.feishu_mobile" type="tel" autocomplete="off"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
                placeholder="绑定手机号（留空不修改）" />
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">飞书 Union ID</label>
              <input v-model="userForm.feishu_union_id" type="text" autocomplete="off"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                placeholder="on_xxxxxxxxxxxxxxxx（留空不修改）" />
            </div>
          </div>
          <div class="flex gap-3 pt-2">
            <button type="submit"
              class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              {{ isEditUser ? '保存修改' : '创建用户' }}
            </button>
            <button type="button" @click="showUserModal = false"
              class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
              取消
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: 分配RBAC角色 -->
    <div v-if="showRoleModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      @click.self="showRoleModal = false">
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-md">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">分配RBAC角色 — {{ assigningUser?.username }}</h3>
          <button @click="showRoleModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <div class="p-6 space-y-4">
          <div class="text-xs text-text-tertiary">
            当前已分配：
            <span v-if="assignedRoles.length" class="text-[#0ecb81]">
              {{ assignedRoles.map(r => r.role?.role_name || r.role_name || r).join('、') }}
            </span>
            <span v-else class="text-text-secondary">无</span>
          </div>
          <div class="space-y-2 max-h-64 overflow-y-auto">
            <label v-for="role in allRoles" :key="role.role_id"
              class="flex items-center gap-3 px-3 py-2.5 bg-dark-200 rounded-lg cursor-pointer hover:bg-dark-50 transition-colors">
              <input type="checkbox" :value="role.role_id" v-model="selectedRoleIds" class="accent-primary w-4 h-4" />
              <div>
                <div class="text-sm font-medium">{{ role.role_name }}</div>
                <div class="text-xs text-text-tertiary">{{ role.description || role.role_code }}</div>
              </div>
            </label>
            <div v-if="!allRoles.length" class="text-center py-4 text-text-tertiary text-xs">暂无可分配角色</div>
          </div>
          <div class="flex gap-3">
            <button @click="saveAssignedRoles"
              class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              保存
            </button>
            <button @click="showRoleModal = false"
              class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
              取消
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: 新增/编辑账户 -->
    <div v-if="showAccountModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      @click.self="showAccountModal = false">
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">{{ isEditAccount ? '编辑账户' : '新增账户' }}</h3>
          <button @click="showAccountModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="saveAccount" class="p-6 space-y-4">
          <!-- 所属用户（新增时显示） -->
          <div v-if="!isEditAccount">
            <label class="block text-xs text-text-tertiary mb-1">所属用户 *</label>
            <select v-model="accountForm.user_id" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="">-- 选择用户 --</option>
              <option v-for="u in users" :key="u.user_id" :value="u.user_id">{{ u.username }}</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">账户名称 *</label>
            <input v-model="accountForm.account_name" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="例如: 主账户" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">平台 *</label>
            <select v-model="accountForm.platform_id" @change="onPlatformChange"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option :value="1">Binance</option>
              <option :value="2">Bybit</option>
            </select>
          </div>
          <div v-if="accountForm.platform_id === 2" class="flex items-center gap-3">
            <div @click="accountForm.is_mt5_account = !accountForm.is_mt5_account"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                accountForm.is_mt5_account ? 'bg-blue-500' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                accountForm.is_mt5_account ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">这是 MT5 账户</span>
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">API Key *</label>
            <input v-model="accountForm.api_key" required autocomplete="off"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="输入 API Key" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">
              {{ isEditAccount ? 'API Secret（留空不修改）' : 'API Secret *' }}
            </label>
            <input v-model="accountForm.api_secret" type="password" :required="!isEditAccount" autocomplete="new-password"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="输入 API Secret" />
          </div>
          <div v-if="accountForm.platform_id === 2">
            <label class="block text-xs text-text-tertiary mb-1">Passphrase（可选）</label>
            <input v-model="accountForm.passphrase" type="password"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="Bybit API Passphrase" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">杠杆倍数</label>
            <input v-model.number="accountForm.leverage" type="number" min="1" max="500"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              :placeholder="accountForm.platform_id === 1 ? '默认 20x' : '默认 100x'" />
          </div>
          <div class="flex items-center gap-3">
            <div @click="accountForm.is_default = !accountForm.is_default"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                accountForm.is_default ? 'bg-[#f0b90b]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                accountForm.is_default ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">设为默认账户</span>
          </div>
          <div class="flex gap-3 pt-2">
            <button type="submit"
              class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              {{ isEditAccount ? '保存修改' : '创建账户' }}
            </button>
            <button type="button" @click="showAccountModal = false"
              class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
              取消
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: 新增/编辑MT5客户端 -->
    <div v-if="showMT5Modal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      @click.self="showMT5Modal = false">
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">{{ isEditMT5 ? '编辑MT5客户端' : '新增MT5客户端' }}</h3>
          <button @click="showMT5Modal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="saveMT5" class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-text-tertiary mb-1">客户端名称 *</label>
            <input v-model="mt5Form.client_name" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="例如: 主客户端、备用客户端1" />
            <p class="text-xs text-text-tertiary mt-1">每个账户下的客户端名称必须唯一</p>
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">MT5 登录账号 *</label>
            <input v-model="mt5Form.mt5_login" required pattern="[0-9]+"
              autocomplete="off"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="例如: 3971962（纯数字）" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">
              MT5 密码{{ isEditMT5 ? '（留空不修改）' : ' *' }}
            </label>
            <input v-model="mt5Form.mt5_password" type="password" :required="!isEditMT5"
              autocomplete="new-password"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="输入MT5登录密码" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">密码类型 *</label>
            <select v-model="mt5Form.password_type" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="primary">主密码（可交易）</option>
              <option value="readonly">只读密码（仅查看）</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">MT5 服务器 *</label>
            <input v-model="mt5Form.mt5_server" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="例如: Bybit-Live-2" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">优先级 *</label>
            <input v-model.number="mt5Form.priority" type="number" required min="1" max="100"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="1–100，数字越小优先级越高" />
            <p class="text-xs text-text-tertiary mt-1">用于多客户端故障转移排序</p>
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">MT5桥接地址</label>
            <input v-model="mt5Form.bridge_url"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="例如: http://54.249.66.53:8001" />
            <p class="text-xs text-text-tertiary mt-1">MT5微服务桥接节点地址，留空使用系统默认</p>
          </div>
          <div class="flex items-center gap-3">
            <div @click="mt5Form.is_active = !mt5Form.is_active"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                mt5Form.is_active ? 'bg-[#0ecb81]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                mt5Form.is_active ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">启用此客户端</span>
          </div>
          <div class="flex gap-3 pt-2">
            <button type="submit"
              class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              {{ isEditMT5 ? '保存' : '创建' }}
            </button>
            <button type="button" @click="showMT5Modal = false"
              class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
              取消
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: 部署MT5实例 -->
    <div v-if="showDeployModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      @click.self="showDeployModal = false">
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">部署新 MT5 实例</h3>
          <button @click="showDeployModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="deployInstance" class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-text-tertiary mb-1">实例名称 *</label>
            <input v-model="deployForm.instance_name" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="例如: MT5-8003" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">服务器IP *</label>
            <input v-model="deployForm.server_ip" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="例如: 54.249.66.53" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">服务端口 *</label>
            <input v-model.number="deployForm.service_port" type="number" required min="1024" max="65535"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="例如: 8003" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">MT5路径 *</label>
            <input v-model="deployForm.mt5_path" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="例如: D:\MetaTrader 5-03\terminal64.exe" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">MT5数据目录</label>
            <input v-model="deployForm.mt5_data_path"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="可选，例如: D:\MetaTrader 5-03" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">部署路径 *</label>
            <input v-model="deployForm.deploy_path" required
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
              placeholder="例如: D:\hustle-mt5-8003" />
          </div>
          <div class="flex items-center gap-3">
            <div @click="deployForm.is_portable = !deployForm.is_portable"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                deployForm.is_portable ? 'bg-primary' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                deployForm.is_portable ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">便携版</span>
          </div>
          <div class="flex items-center gap-3">
            <div @click="deployForm.auto_start = !deployForm.auto_start"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                deployForm.auto_start ? 'bg-[#0ecb81]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                deployForm.auto_start ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">开机自启</span>
          </div>
          <div class="flex gap-3 pt-2">
            <button type="submit" :disabled="deploying"
              class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors disabled:opacity-50">
              {{ deploying ? '部署中...' : '部署' }}
            </button>
            <button type="button" @click="showDeployModal = false"
              class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
              取消
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: IPIPGO 静态IP代理配置 -->
    <div v-if="showProxyModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      @click.self="showProxyModal = false">
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-md">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <div>
            <h3 class="font-bold">IPIPGO 静态IP代理</h3>
            <p class="text-xs text-text-tertiary mt-0.5">{{ proxyTargetAcc?.account_name }}</p>
          </div>
          <button @click="showProxyModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="saveProxyConfig" class="p-6 space-y-4">
          <p class="text-xs text-text-tertiary bg-dark-200 rounded-lg p-3">
            配置 IPIPGO 独享静态IP，用于 Binance/Bybit API 请求防封。留空所有字段可清除代理配置（使用服务器直连）。
          </p>
          <div class="grid grid-cols-2 gap-3">
            <div class="col-span-2">
              <label class="block text-xs text-text-tertiary mb-1">代理类型</label>
              <select v-model="proxyForm.proxy_type"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
                <option value="socks5">SOCKS5</option>
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">主机地址 (Host)</label>
              <input v-model="proxyForm.host"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                placeholder="例: 1.2.3.4 或 proxy.ipipgo.com" />
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">端口 (Port)</label>
              <input v-model.number="proxyForm.port" type="number" min="1" max="65535"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                placeholder="例: 1080" />
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">用户名</label>
              <input v-model="proxyForm.username"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                placeholder="IPIPGO 用户名" />
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1">密码</label>
              <input v-model="proxyForm.password" type="password"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                placeholder="IPIPGO 密码" />
            </div>
            <div class="col-span-2">
              <label class="block text-xs text-text-tertiary mb-1">地区备注（可选）</label>
              <input v-model="proxyForm.region"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
                placeholder="例: 日本-东京, 新加坡" />
            </div>
          </div>
          <div class="flex gap-3 pt-2">
            <button type="submit"
              class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              保存配置
            </button>
            <button type="button" @click="clearProxyConfig"
              class="py-2 px-4 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded-lg text-sm border border-[#f6465d]/20 transition-colors">
              清除
            </button>
            <button type="button" @click="showProxyModal = false"
              class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
              取消
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Toast 提示 -->
    <div class="fixed bottom-6 right-6 z-50 space-y-2 pointer-events-none">
      <transition-group name="toast">
        <div v-for="t in toasts" :key="t.id"
          :class="['px-4 py-3 rounded-xl shadow-xl text-sm font-medium pointer-events-auto flex items-center gap-2',
            t.type === 'success' ? 'bg-[#0ecb81] text-dark-300' : 'bg-[#f6465d] text-white']">
          <span>{{ t.type === 'success' ? '✓' : '✕' }}</span>
          <span>{{ t.msg }}</span>
        </div>
      </transition-group>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/services/api.js'
import dayjs from 'dayjs'

// ── Tabs ──────────────────────────────────────────────────────
const tabs = [
  { id: 'users',    label: '用户账号' },
  { id: 'accounts', label: '绑定账户' },
  { id: 'mt5',      label: 'MT5管理' },
]
const activeTab = ref('users')
const mt5SubTab = ref('clients') // 'clients' or 'instances'

// 切换 tab 时自动加载数据
watch(activeTab, (tab) => {
  if (tab === 'accounts' && !accounts.value.length) loadUserAccounts()
  if (tab === 'mt5') autoLoadMT5Tab()
})

// ── Toast helpers ─────────────────────────────────────────────
const toasts = ref([])
function toast(msg, type = 'success') {
  const id = Date.now() + Math.random()
  toasts.value.push({ id, msg, type })
  setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id) }, 3000)
}
function apiErr(label, e) {
  const detail = e?.response?.data?.detail || e?.message || ''
  toast(detail ? `${label}: ${detail}` : label, 'error')
}

// ── Formatters ────────────────────────────────────────────────
function fmtDate(d) {
  if (!d) return '-'
  return dayjs(d).format('MM-DD HH:mm')
}
function maskStr(s) {
  if (!s) return 'N/A'
  if (s.length <= 8) return '****'
  return s.slice(0, 4) + '****' + s.slice(-4)
}
function maskSecret(s) {
  if (!s) return 'N/A'
  return '●'.repeat(16)
}
function getPlatformName(pid, mt5) {
  if (pid === 1) return 'Binance'
  return mt5 ? 'Bybit MT5' : 'Bybit'
}

// ══════════════════════════════════════════
// Tab 1 — 用户账号
// ══════════════════════════════════════════
const users        = ref([])
const usersLoading = ref(false)
const showUserModal = ref(false)
const isEditUser    = ref(false)
const currentUser   = ref(null)
const userForm = ref({ username: '', email: '', password: '', role: '交易员', is_active: true, feishu_open_id: '', feishu_mobile: '', feishu_union_id: '' })

const adminCount = computed(() =>
  users.value.filter(u =>
    (u.rbac_roles || []).some(r => (r.role_name || r || '').includes('管理员'))
  ).length
)

async function loadUsers() {
  usersLoading.value = true
  try {
    const r = await api.get('/api/v1/users/')
    users.value = r.data?.users || r.data || []
  } catch (e) { apiErr('加载用户失败', e) }
  finally { usersLoading.value = false }
}

function openAddUser() {
  isEditUser.value = false
  currentUser.value = null
  userForm.value = { username: '', email: '', password: '', role: '交易员', is_active: true, feishu_open_id: '', feishu_mobile: '', feishu_union_id: '' }
  showUserModal.value = true
}

function openEditUser(u) {
  isEditUser.value = true
  currentUser.value = u
  userForm.value = {
    username: u.username, email: u.email || '', password: '', role: u.role || '交易员',
    is_active: u.is_active,
    feishu_open_id:  u.feishu_open_id  || '',
    feishu_mobile:   u.feishu_mobile   || '',
    feishu_union_id: u.feishu_union_id || '',
  }
  showUserModal.value = true
}

async function saveUser() {
  try {
    if (isEditUser.value) {
      const data = { email: userForm.value.email || null, role: userForm.value.role, is_active: userForm.value.is_active }
      if (userForm.value.password)        data.password        = userForm.value.password
      if (userForm.value.feishu_open_id  !== '') data.feishu_open_id  = userForm.value.feishu_open_id  || null
      if (userForm.value.feishu_mobile   !== '') data.feishu_mobile   = userForm.value.feishu_mobile   || null
      if (userForm.value.feishu_union_id !== '') data.feishu_union_id = userForm.value.feishu_union_id || null
      await api.put(`/api/v1/users/${currentUser.value.user_id}`, data)
      toast('用户已更新')
    } else {
      await api.post('/api/v1/users/', userForm.value)
      toast('用户已创建')
    }
    showUserModal.value = false
    await loadUsers()
  } catch (e) { apiErr('保存用户失败', e) }
}

async function toggleUserStatus(u) {
  try {
    await api.put(`/api/v1/users/${u.user_id}`, { is_active: !u.is_active })
    toast(u.is_active ? '用户已禁用' : '用户已启用')
    await loadUsers()
  } catch (e) { apiErr('操作失败', e) }
}

async function deleteUser(u) {
  if (!confirm(`确定要删除用户「${u.username}」吗？此操作不可恢复！`)) return
  try {
    await api.delete(`/api/v1/users/${u.user_id}`)
    toast('用户已删除')
    await loadUsers()
  } catch (e) { apiErr('删除失败', e) }
}

// ── 分配 RBAC 角色 ────────────────────────────────────────────
const showRoleModal   = ref(false)
const assigningUser   = ref(null)
const allRoles        = ref([])
const assignedRoles   = ref([])
const selectedRoleIds = ref([])

async function openAssignRole(u) {
  assigningUser.value = u
  selectedRoleIds.value = []
  assignedRoles.value = []
  showRoleModal.value = true
  try {
    const [rolesRes, userRolesRes] = await Promise.all([
      api.get('/api/v1/rbac/roles'),
      api.get(`/api/v1/rbac/users/${u.user_id}/roles`)
    ])
    allRoles.value     = rolesRes.data || []
    assignedRoles.value = userRolesRes.data || []
    selectedRoleIds.value = assignedRoles.value
      .map(r => r.role?.role_id || r.role_id)
      .filter(Boolean)
  } catch (e) { apiErr('加载角色失败', e) }
}

async function saveAssignedRoles() {
  try {
    const uid = assigningUser.value.user_id
    // 先清除全部指派角色
    for (const r of assignedRoles.value) {
      const rid = r.role?.role_id || r.role_id
      if (rid) await api.delete(`/api/v1/rbac/users/${uid}/roles/${rid}`).catch(() => {})
    }
    // 再重新指派
    for (const rid of selectedRoleIds.value) {
      await api.post(`/api/v1/rbac/users/${uid}/roles`, { role_id: rid }).catch(() => {})
    }
    toast('角色分配已保存')
    showRoleModal.value = false
    await loadUsers()
  } catch (e) { apiErr('保存角色失败', e) }
}

// ══════════════════════════════════════════
// Tab 2 — 绑定账户
// ══════════════════════════════════════════
const accounts              = ref([])
const accountsLoading       = ref(false)
const selectedAccountUserId = ref('')
const showAccountModal      = ref(false)
const isEditAccount         = ref(false)
const currentAccount        = ref(null)
const accountForm = ref({
  user_id: '', account_name: '', platform_id: 2,
  api_key: '', api_secret: '', passphrase: '',
  is_mt5_account: false, is_default: false, is_active: true, leverage: 100
})

async function loadUserAccounts() {
  accountsLoading.value = true
  accounts.value = []
  try {
    // Backend returns accounts for the JWT user only — no user_id filter supported
    // Use trailing slash to avoid 307 redirect loop
    const r = await api.get('/api/v1/accounts')
    const data = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    // Attach username from users list
    accounts.value = data.map(a => {
      const owner = users.value.find(u => u.user_id === (a.user_id || ''))
      return { ...a, _username: owner?.username || '' }
    })
  } catch (e) { apiErr('加载账户失败', e) }
  finally { accountsLoading.value = false }
}

function onPlatformChange() {
  if (accountForm.value.platform_id === 1) {
    accountForm.value.is_mt5_account = false
    accountForm.value.leverage = 20
  } else {
    accountForm.value.leverage = 100
  }
}

function openAddAccount() {
  isEditAccount.value = false
  currentAccount.value = null
  accountForm.value = {
    user_id: selectedAccountUserId.value || '',
    account_name: '', platform_id: 2, api_key: '', api_secret: '',
    passphrase: '', is_mt5_account: false, is_default: false, is_active: true, leverage: 100
  }
  showAccountModal.value = true
}

async function openEditAccount(acc) {
  isEditAccount.value = true
  currentAccount.value = acc
  accountForm.value = {
    account_name: acc.account_name, platform_id: acc.platform_id,
    api_key: acc.api_key || '', api_secret: '', passphrase: '',
    is_mt5_account: acc.is_mt5_account, is_default: acc.is_default,
    is_active: acc.is_active, leverage: acc.leverage || (acc.platform_id === 1 ? 20 : 100)
  }
  showAccountModal.value = true
  // Load actual API secret from backend (stored encrypted, shown on edit)
  try {
    const r = await api.get(`/api/v1/accounts/${acc.account_id}/secret`)
    accountForm.value.api_secret  = r.data.api_secret  || ''
    accountForm.value.passphrase  = r.data.passphrase  || ''
  } catch { /* admin may not have bypass yet — user can re-enter manually */ }
}

// IPIPGO proxy config
const showProxyModal  = ref(false)
const proxyTargetAcc  = ref(null)
const proxyForm = ref({ proxy_type: 'socks5', host: '', port: null, username: '', password: '', region: '' })

function openProxyConfig(acc) {
  proxyTargetAcc.value = acc
  const cfg = acc.proxy_config || {}
  proxyForm.value = {
    proxy_type: cfg.proxy_type || 'socks5',
    host:       cfg.host       || '',
    port:       cfg.port       || null,
    username:   cfg.username   || '',
    password:   cfg.password   || '',
    region:     cfg.region     || '',
  }
  showProxyModal.value = true
}

async function saveProxyConfig() {
  const acc = proxyTargetAcc.value
  if (!acc) return
  const cfg = proxyForm.value.host ? {
    proxy_type: proxyForm.value.proxy_type,
    host:       proxyForm.value.host,
    port:       proxyForm.value.port,
    username:   proxyForm.value.username || null,
    password:   proxyForm.value.password || null,
    region:     proxyForm.value.region   || null,
  } : null
  try {
    await api.put(`/api/v1/accounts/${acc.account_id}`, { proxy_config: cfg })
    toast('代理配置已保存')
    showProxyModal.value = false
    await loadUserAccounts()
  } catch (e) { apiErr('保存代理配置失败', e) }
}

async function clearProxyConfig() {
  const acc = proxyTargetAcc.value
  if (!acc) return
  try {
    await api.put(`/api/v1/accounts/${acc.account_id}`, { proxy_config: null })
    toast('代理配置已清除')
    showProxyModal.value = false
    await loadUserAccounts()
  } catch (e) { apiErr('清除代理配置失败', e) }
}

async function saveAccount() {
  try {
    if (isEditAccount.value) {
      const data = {
        account_name:   accountForm.value.account_name,
        is_default:     accountForm.value.is_default,
        is_active:      accountForm.value.is_active,
        is_mt5_account: accountForm.value.is_mt5_account,
        leverage:       accountForm.value.leverage,
      }
      if (accountForm.value.api_key)    data.api_key    = accountForm.value.api_key
      if (accountForm.value.api_secret) data.api_secret = accountForm.value.api_secret
      if (accountForm.value.passphrase) data.passphrase = accountForm.value.passphrase
      await api.put(`/api/v1/accounts/${currentAccount.value.account_id}`, data)
      toast('账户已更新')
    } else {
      if (!accountForm.value.user_id) { toast('请选择所属用户', 'error'); return }
      // Strip user_id from body — AccountCreate schema doesn't accept it (backend uses JWT)
      const { user_id: _uid, ...postData } = accountForm.value
      await api.post('/api/v1/accounts', postData)
      toast('账户已创建')
    }
    showAccountModal.value = false
    await loadUserAccounts()
  } catch (e) { apiErr('保存账户失败', e) }
}

async function toggleAccount(acc) {
  try {
    await api.put(`/api/v1/accounts/${acc.account_id}`, { is_active: !acc.is_active })
    await loadUserAccounts()
  } catch (e) { apiErr('切换状态失败', e) }
}

async function deleteAccount(acc) {
  if (acc.is_active) { toast('请先禁用账户再删除', 'error'); return }
  if (acc.is_default) { toast('请先取消默认设置再删除', 'error'); return }
  if (!confirm(`确定要删除账户「${acc.account_name}」吗？此操作不可恢复！`)) return
  try {
    await api.delete(`/api/v1/accounts/${acc.account_id}`)
    toast('账户已删除')
    await loadUserAccounts()
  } catch (e) { apiErr('删除失败', e) }
}

// ══════════════════════════════════════════
// Tab 3 — MT5客户端
// ══════════════════════════════════════════
const mt5Clients           = ref([])
const mt5Loading           = ref(false)
const mt5SelectedUserId    = ref('')
const mt5SelectedAccountId = ref('')
const mt5Accounts          = ref([])
const showMT5Modal         = ref(false)
const isEditMT5            = ref(false)
const currentMT5           = ref(null)
const mt5Form = ref({
  client_name: '', mt5_login: '', mt5_password: '', password_type: 'primary',
  mt5_server: '', bridge_url: '', proxy_id: null,
  priority: 1, is_active: true
})

async function onMt5UserChange() {
  mt5SelectedAccountId.value = ''
  mt5Clients.value = []
  mt5Accounts.value = []
  if (!mt5SelectedUserId.value) return
  try {
    const r = await api.get('/api/v1/accounts')
    const all = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    // 只显示 Bybit / MT5 账户
    mt5Accounts.value = all.filter(a => a.platform_id === 2)
  } catch (e) { apiErr('加载账户失败', e) }
}

async function autoLoadMT5Tab() {
  if (!users.value.length) return
  // 自动选第一个用户
  if (!mt5SelectedUserId.value) mt5SelectedUserId.value = users.value[0].user_id
  await onMt5UserChange()
  // 自动选第一个 MT5 账户
  if (mt5Accounts.value.length && !mt5SelectedAccountId.value) {
    mt5SelectedAccountId.value = mt5Accounts.value[0].account_id
    await loadMT5Clients()
  }
}

async function loadMT5Clients() {
  if (!mt5SelectedAccountId.value) return
  mt5Loading.value = true
  try {
    const r = await api.get(`/api/v1/accounts/${mt5SelectedAccountId.value}/mt5-clients`)
    mt5Clients.value = Array.isArray(r.data) ? r.data : (r.data?.clients ?? [])
  } catch (e) { apiErr('加载MT5客户端失败', e) }
  finally { mt5Loading.value = false }
}

function getMT5BorderColor(client) {
  if (client.connection_status === 'connected')  return 'border-[#0ecb81]/40'
  if (client.connection_status === 'connecting') return 'border-[#f0b90b]/40'
  if (client.connection_status === 'error')      return 'border-[#f6465d]/40'
  return 'border-border-primary'
}

function getMT5StatusClass(status) {
  return ({
    connected:    'bg-[#0ecb81]/10 text-[#0ecb81]',
    connecting:   'bg-[#f0b90b]/10 text-[#f0b90b]',
    disconnected: 'bg-dark-200 text-text-tertiary',
    error:        'bg-[#f6465d]/10 text-[#f6465d]',
  })[status] || 'bg-dark-200 text-text-tertiary'
}

function getMT5StatusText(status) {
  return ({ connected: '已连接', connecting: '连接中', disconnected: '未连接', error: '错误' })[status] || (status || '未知')
}

function openAddMT5() {
  isEditMT5.value = false
  currentMT5.value = null
  mt5Form.value = {
    client_name: '', mt5_login: '', mt5_password: '', password_type: 'primary',
    mt5_server: '', bridge_url: '', proxy_id: null,
    priority: 1, is_active: true
  }
  showMT5Modal.value = true
}

function openEditMT5(client) {
  isEditMT5.value = true
  currentMT5.value = client
  mt5Form.value = {
    client_name:   client.client_name,
    mt5_login:     client.mt5_login,
    mt5_password:  '',
    bridge_url:    client.bridge_url || '',
    password_type: client.password_type || 'primary',
    mt5_server:    client.mt5_server,
    proxy_id:      client.proxy_id || null,
    priority:      client.priority,
    is_active:     client.is_active,
  }
  showMT5Modal.value = true
}

async function saveMT5() {
  try {
    if (isEditMT5.value) {
      const data = { ...mt5Form.value }
      if (!data.mt5_password) delete data.mt5_password
      await api.put(`/api/v1/mt5-clients/${currentMT5.value.client_id}`, data)
      toast('MT5客户端已更新')
    } else {
      const data = { ...mt5Form.value, account_id: mt5SelectedAccountId.value }
      await api.post(`/api/v1/accounts/${mt5SelectedAccountId.value}/mt5-clients`, data)
      toast('MT5客户端已创建')
    }
    showMT5Modal.value = false
    await loadMT5Clients()
  } catch (e) { apiErr('保存失败', e) }
}

async function toggleMT5Active(client) {
  try {
    await api.put(`/api/v1/mt5-clients/${client.client_id}`, { is_active: !client.is_active })
    await loadMT5Clients()
  } catch (e) { apiErr('切换失败', e) }
}

async function connectMT5(client) {
  try {
    await api.post(`/api/v1/mt5-clients/${client.client_id}/connect`)
    toast('连接指令已发送')
    setTimeout(loadMT5Clients, 2000)
  } catch (e) { apiErr('连接失败', e) }
}

async function disconnectMT5(client) {
  try {
    await api.post(`/api/v1/mt5-clients/${client.client_id}/disconnect`)
    toast('断开指令已发送')
    setTimeout(loadMT5Clients, 2000)
  } catch (e) { apiErr('断开失败', e) }
}

async function deleteMT5(client) {
  if (!confirm(`确定要删除MT5客户端「${client.client_name}」吗？`)) return
  try {
    await api.delete(`/api/v1/mt5-clients/${client.client_id}`)
    toast('MT5客户端已删除')
    await loadMT5Clients()
  } catch (e) { apiErr('删除失败', e) }
}

// ══════════════════════════════════════════
// MT5 实例管理
// ══════════════════════════════════════════
const mt5Instances = ref([])
const instancesLoading = ref(false)
const showDeployModal = ref(false)
const deploying = ref(false)
const deployForm = ref({
  instance_name: '',
  server_ip: '54.249.66.53',
  service_port: 8003,
  mt5_path: '',
  mt5_data_path: '',
  deploy_path: '',
  is_portable: false,
  auto_start: true
})

async function loadMT5Instances() {
  instancesLoading.value = true
  try {
    const r = await api.get('/api/v1/mt5/instances')
    mt5Instances.value = r.data || []
  } catch (e) { apiErr('加载实例失败', e) }
  finally { instancesLoading.value = false }
}

function openDeployInstance() {
  deployForm.value = {
    instance_name: '',
    server_ip: '54.249.66.53',
    service_port: 8003,
    mt5_path: '',
    mt5_data_path: '',
    deploy_path: '',
    is_portable: false,
    auto_start: true
  }
  showDeployModal.value = true
}

async function deployInstance() {
  deploying.value = true
  try {
    await api.post('/api/v1/mt5/instances', deployForm.value)
    toast('实例部署成功')
    showDeployModal.value = false
    await loadMT5Instances()
  } catch (e) { apiErr('部署失败', e) }
  finally { deploying.value = false }
}

async function controlInstance(inst, action) {
  try {
    await api.post(`/api/v1/mt5/instances/${inst.instance_id}/control`, { action })
    toast(`${action === 'start' ? '启动' : action === 'stop' ? '停止' : '重启'}成功`)
    await loadMT5Instances()
  } catch (e) { apiErr('操作失败', e) }
}

async function refreshInstanceStatus(inst) {
  try {
    await api.get(`/api/v1/mt5/instances/${inst.instance_id}/status`)
    toast('状态已刷新')
    await loadMT5Instances()
  } catch (e) { apiErr('刷新失败', e) }
}

async function deleteInstance(inst) {
  if (!confirm(`确定要删除实例「${inst.instance_name}」吗？`)) return
  try {
    await api.delete(`/api/v1/mt5/instances/${inst.instance_id}`)
    toast('实例已删除')
    await loadMT5Instances()
  } catch (e) { apiErr('删除失败', e) }
}

function getInstanceBorderColor(status) {
  if (status === 'running') return 'border-[#0ecb81]/40'
  if (status === 'stopped') return 'border-border-primary'
  if (status === 'error') return 'border-[#f6465d]/40'
  return 'border-[#f0b90b]/40'
}

function getInstanceStatusClass(status) {
  return ({
    running: 'bg-[#0ecb81]/10 text-[#0ecb81]',
    stopped: 'bg-dark-200 text-text-tertiary',
    error: 'bg-[#f6465d]/10 text-[#f6465d]',
  })[status] || 'bg-[#f0b90b]/10 text-[#f0b90b]'
}

function getInstanceStatusText(status) {
  return ({ running: '运行中', stopped: '已停止', error: '错误' })[status] || '未知'
}

// ── 初始化 ────────────────────────────────────────────────────
onMounted(async () => {
  await loadUsers()
  // 账户 tab 初始不加载（等用户切换到该 tab 再触发）
})

// 切换到 MT5 实例子页面时自动加载
watch(mt5SubTab, (tab) => {
  if (tab === 'instances' && !mt5Instances.value.length) loadMT5Instances()
})
</script>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from { opacity: 0; transform: translateX(16px); }
.toast-leave-to   { opacity: 0; transform: translateX(16px); }
</style>
