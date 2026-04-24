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
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
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
        <div class="bg-dark-100 rounded-xl border border-border-primary p-3.5">
          <div class="text-xs text-text-tertiary mb-1">子账号</div>
          <div class="text-xl font-bold font-mono text-purple-300">{{ subAccountCount }}</div>
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
        <!-- Desktop table -->
        <div class="hidden md:block overflow-x-auto">
          <table class="w-full text-xs min-w-[760px]">
            <thead>
              <tr class="border-b border-border-secondary text-text-tertiary">
                <th class="text-left px-4 py-2.5 whitespace-nowrap">用户名</th>
                <th class="text-left px-3 py-2.5 whitespace-nowrap">邮箱</th>
                <th class="text-left px-3 py-2.5 whitespace-nowrap">用户类型</th>
                <th class="text-left px-3 py-2.5 whitespace-nowrap">RBAC角色</th>
                <th class="text-center px-3 py-2.5 whitespace-nowrap">状态</th>
                <th class="text-left px-3 py-2.5 whitespace-nowrap">创建时间</th>
                <th class="text-center px-4 py-2.5 whitespace-nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="usersLoading">
                <td colspan="7" class="text-center py-10 text-text-tertiary">加载中...</td>
              </tr>
              <tr v-else-if="!users.length">
                <td colspan="7" class="text-center py-10 text-text-tertiary">暂无用户数据</td>
              </tr>
              <tr v-for="u in users" :key="u.user_id"
                class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="px-4 py-2.5 font-medium whitespace-nowrap">{{ u.username }}</td>
                <td class="px-3 py-2.5 text-text-tertiary whitespace-nowrap">{{ u.email || '-' }}</td>
                <td class="px-3 py-2.5 whitespace-nowrap">
                  <span v-if="u.is_subaccount"
                    class="px-1.5 py-0.5 rounded text-[10px] bg-purple-500/10 text-purple-300">子账号</span>
                  <span v-else-if="isAdminUser(u)"
                    class="px-1.5 py-0.5 rounded text-[10px] bg-[#f0b90b]/10 text-[#f0b90b]">管理员</span>
                  <span v-else
                    class="px-1.5 py-0.5 rounded text-[10px] bg-[#3370ff]/10 text-[#3370ff]">交易员</span>
                </td>
                <td class="px-3 py-2.5 whitespace-nowrap">
                  <div class="flex flex-wrap gap-1">
                    <span v-for="r in (u.rbac_roles || [])" :key="r.role_id || r"
                      class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/10 text-[#0ecb81]">
                      {{ r.role_name || r }}
                    </span>
                    <span v-if="!u.rbac_roles?.length" class="text-text-tertiary">未分配</span>
                  </div>
                </td>
                <td class="px-3 py-2.5 text-center whitespace-nowrap">
                  <span :class="u.is_active
                    ? 'bg-[#0ecb81]/10 text-[#0ecb81] px-1.5 py-0.5 rounded'
                    : 'bg-[#f6465d]/10 text-[#f6465d] px-1.5 py-0.5 rounded'">
                    {{ u.is_active ? '启用' : '禁用' }}
                  </span>
                </td>
                <td class="px-3 py-2.5 text-text-tertiary font-mono whitespace-nowrap">{{ fmtDate(u.create_time) }}</td>
                <td class="px-4 py-2.5 text-center whitespace-nowrap">
                  <div class="flex items-center justify-center gap-2">
                    <button @click="openEditUser(u)"
                      class="text-primary hover:text-primary-hover text-xs transition-colors">编辑</button>
                    <button @click="openSubAccountModal(u)" v-if="!u.is_subaccount"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="hasSubAccounts(u) ? 'text-[#0ecb81]' : 'text-purple-400'">
                      {{ hasSubAccounts(u) ? '子账号✓' : '子账号' }}
                    </button>
                    <span v-else class="text-[10px] text-purple-300">子账号身份</span>
                    <button @click="openAssignRole(u)"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="(u.rbac_roles?.length) ? 'text-[#0ecb81]' : 'text-[#3370ff]'">
                      {{ (u.rbac_roles?.length) ? '分配角色✓' : '分配角色' }}
                    </button>
                    <button @click="openNotifConfig(u)"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="(u.notif_subscription_count > 0) ? 'text-[#0ecb81]' : 'text-[#3370ff]'">
                      {{ (u.notif_subscription_count > 0) ? '通知分配✓' : '通知分配' }}
                    </button>
                    <button @click="openHedgeRatio(u)"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="u.hedge_ratio_enabled ? 'text-[#0ecb81]' : 'text-[#f0b90b]'">
                      {{ u.hedge_ratio_enabled ? '对冲倍数✓' : '对冲倍数' }}
                    </button>
                    <button @click="openOpenclawAccess(u)"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="u.openclaw_enabled ? 'text-[#0ecb81]' : 'text-[#3370ff]'">
                      {{ u.openclaw_enabled ? '智能体量化✓' : '智能体量化' }}
                    </button>
                    <button @click="openFundViewAccess(u)"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="u.fund_view_enabled ? 'text-[#0ecb81]' : 'text-[#f0b90b]'">
                      {{ u.fund_view_enabled ? '查看资金✓' : '查看资金' }}
                    </button>
                    <button @click="toggleUserStatus(u)"
                      class="hover:opacity-80 text-xs transition-colors"
                      :class="u.is_active ? 'text-[#0ecb81]' : 'text-[#f0b90b]'">
                      {{ u.is_active ? '已启用✓' : '已禁用' }}
                    </button>
                    <button @click="deleteUser(u)"
                      class="text-[#f6465d] hover:opacity-80 text-xs transition-colors">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Mobile card list -->
        <div class="md:hidden space-y-3 p-3">
          <div v-if="usersLoading" class="text-center py-8 text-text-tertiary text-sm">加载中...</div>
          <div v-else-if="!users.length" class="text-center py-8 text-text-tertiary text-sm">暂无用户数据</div>
          <div v-for="u in users" :key="u.user_id"
            class="bg-dark-200 rounded-xl p-3 space-y-2 border border-border-secondary">
            <div class="flex items-center justify-between">
              <div class="font-bold text-sm">{{ u.username }}</div>
              <span :class="u.is_active ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#f6465d]/10 text-[#f6465d]'"
                class="px-1.5 py-0.5 rounded text-xs">
                {{ u.is_active ? '启用' : '禁用' }}
              </span>
            </div>
            <div class="text-xs text-text-tertiary">{{ u.email || '-' }}</div>
            <div class="flex flex-wrap gap-1">
              <span v-for="r in (u.rbac_roles || [])" :key="r.role_id || r"
                class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/10 text-[#0ecb81]">
                {{ r.role_name || r }}
              </span>
              <span v-if="!u.rbac_roles?.length" class="text-text-tertiary text-xs">未分配角色</span>
            </div>
            <div class="text-xs text-text-tertiary font-mono">{{ fmtDate(u.create_time) }}</div>
            <div class="grid grid-cols-4 gap-1.5 pt-2 border-t border-border-primary">
              <button @click="openEditUser(u)" class="py-1.5 bg-primary/10 text-primary rounded text-xs">编辑</button>
              <button @click="openSubAccountModal(u)" v-if="!u.is_subaccount"
                :class="hasSubAccounts(u) ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-purple-500/10 text-purple-300'"
                class="py-1.5 rounded text-xs">{{ hasSubAccounts(u) ? '子账号✓' : '子账号' }}</button>
              <span v-else class="py-1.5 text-[10px] text-purple-300 text-center">子账号身份</span>
              <button @click="openAssignRole(u)"
                :class="(u.rbac_roles?.length) ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#3370ff]/10 text-[#3370ff]'"
                class="py-1.5 rounded text-xs">{{ (u.rbac_roles?.length) ? '角色✓' : '分配角色' }}</button>
              <button @click="openNotifConfig(u)"
                :class="(u.notif_subscription_count > 0) ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#3370ff]/10 text-[#3370ff]'"
                class="py-1.5 rounded text-xs">{{ (u.notif_subscription_count > 0) ? '通知✓' : '通知分配' }}</button>
              <button @click="openHedgeRatio(u)"
                :class="u.hedge_ratio_enabled ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#f0b90b]/10 text-[#f0b90b]'"
                class="py-1.5 rounded text-xs">{{ u.hedge_ratio_enabled ? '对冲✓' : '对冲倍数' }}</button>
              <button @click="openOpenclawAccess(u)"
                :class="u.openclaw_enabled ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#3370ff]/10 text-[#3370ff]'"
                class="py-1.5 rounded text-xs">{{ u.openclaw_enabled ? '智能体✓' : '智能体量化' }}</button>
              <button @click="openFundViewAccess(u)"
                :class="u.fund_view_enabled ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#f0b90b]/10 text-[#f0b90b]'"
                class="py-1.5 rounded text-xs">{{ u.fund_view_enabled ? '查看资金✓' : '查看资金' }}</button>
              <button @click="toggleUserStatus(u)"
                :class="u.is_active ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#f0b90b]/10 text-[#f0b90b]'"
                class="py-1.5 rounded text-xs">{{ u.is_active ? '已启用✓' : '已禁用' }}</button>
              <button @click="deleteUser(u)" class="py-1.5 bg-[#f6465d]/10 text-[#f6465d] rounded text-xs">删除</button>
            </div>
          </div>
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
                <span v-if="acc.account_role === 'primary'" class="px-1.5 py-0.5 rounded text-xs bg-[#0ecb81]/10 text-[#0ecb81]">主账号</span>
                <span v-if="acc.account_role === 'hedge'" class="px-1.5 py-0.5 rounded text-xs bg-[#f0b90b]/10 text-[#f0b90b]">对冲账号</span>
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
              <div class="flex items-center gap-1.5">
                <span v-if="acc.proxy_config" class="px-1.5 py-0.5 rounded text-xs"
                  :class="accProxyStatusClass(acc)">
                  {{ accProxyStatusText(acc) }}
                </span>
                <button @click="openProxyConfig(acc)"
                  class="px-1.5 py-0.5 bg-dark-50 hover:bg-dark-100 border border-border-primary rounded text-text-secondary transition-colors">
                  {{ acc.proxy_config ? '编辑' : '配置' }}
                </button>
              </div>
            </div>
            <div v-if="acc.proxy_config" class="space-y-1">
              <div class="flex justify-between items-center">
                <span class="text-text-tertiary">IP地址:</span>
                <span class="font-mono text-text-secondary">{{ acc.proxy_config.host || '--' }}:{{ acc.proxy_config.port || '--' }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-text-tertiary">类型:</span>
                <span class="font-mono text-text-secondary uppercase">{{ acc.proxy_config.proxy_type || 'socks5' }}</span>
              </div>
              <div v-if="acc.proxy_config.region" class="flex justify-between items-center">
                <span class="text-text-tertiary">地区:</span>
                <span class="text-text-secondary">{{ acc.proxy_config.region }}</span>
              </div>
              <div v-if="acc.proxy_config.allocated_at" class="flex justify-between items-center">
                <span class="text-text-tertiary">分配时间:</span>
                <span class="font-mono text-text-secondary">{{ acc.proxy_config.allocated_at }}</span>
              </div>
              <div v-if="acc.proxy_config.expires_at" class="flex justify-between items-center">
                <span class="text-text-tertiary">过期时间:</span>
                <span class="font-mono" :class="accProxyDaysClass(acc)">
                  {{ acc.proxy_config.expires_at }}
                  <span class="text-text-tertiary font-normal">({{ accProxyDaysLeft(acc) }}天)</span>
                </span>
              </div>
            </div>
            <div v-else class="text-center text-text-tertiary py-1">未配置代理 — 使用服务器直连</div>
          </div>

          <!-- 产品对绑定 -->
          <div class="bg-dark-200 rounded-lg p-2.5 text-xs">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-text-tertiary font-medium">产品对绑定</span>
            </div>
            <div class="flex flex-wrap gap-1">
              <span v-for="tag in getAccountPairTags(acc)" :key="tag.pair"
                class="px-1.5 py-0.5 rounded text-[10px] font-bold"
                :class="tag.side === 'A' ? 'bg-[#0ecb81]/15 text-[#0ecb81]' : 'bg-[#f0b90b]/15 text-[#f0b90b]'">
                {{ tag.pair }}-{{ tag.side === 'A' ? '主' : '对冲' }}
              </span>
              <span v-if="!getAccountPairTags(acc).length" class="text-text-tertiary">未绑定产品对</span>
              <button @click="openPairBindingModal(acc)"
                class="px-1.5 py-0.5 bg-dark-50 hover:bg-dark-100 border border-border-primary rounded text-text-secondary transition-colors ml-auto">
                设置
              </button>
            </div>
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
         Tab 3: MT5客户端
    ═══════════════════════════════════════════ -->
    <div v-if="activeTab === 'mt5'" class="space-y-4">
      <!-- 选择器工具栏 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3 flex items-center gap-3 flex-wrap">
        <span class="text-sm text-text-tertiary whitespace-nowrap">选择用户：</span>
        <select v-model="mt5SelectedUserId" @change="onMt5UserChange"
          class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-xs focus:outline-none focus:border-primary min-w-[160px]">
          <option value="">全部用户</option>
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
      <div v-if="mt5Loading" class="text-center py-12 text-text-tertiary text-sm">加载中...</div>
      <div v-else-if="!mt5Clients.length" class="text-center py-12 text-text-tertiary text-sm">
        暂无MT5客户端，请先选择用户和账户后点击「+ 新增客户端」添加
      </div>

      <!-- 客户端卡片 -->
      <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div v-for="client in mt5Clients" :key="client.client_id"
          class="bg-dark-100 rounded-2xl border p-4 space-y-3 transition-all"
          :class="getMT5BorderColor(client)">

          <!-- 头部 -->
          <div class="flex items-start justify-between">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-bold text-sm">{{ client.client_name }}</span>
                <span v-if="client.platform_name" class="px-1.5 py-0.5 rounded text-[10px] bg-blue-500/10 text-blue-400">{{ client.platform_name }}</span>
                <span v-if="client.is_system_service" class="px-1.5 py-0.5 rounded text-[10px] bg-purple-900/40 text-purple-400">系统服务</span>
              </div>
              <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                <span class="px-1.5 py-0.5 rounded text-xs" :class="getMT5StatusClass(client.connection_status)">
                  {{ getMT5StatusText(client.connection_status) }}
                </span>
                <span v-if="!client.is_active" class="px-1.5 py-0.5 rounded text-xs bg-dark-200 text-text-tertiary">未启用</span>
                <span class="text-xs text-text-tertiary">优先级: {{ client.priority }}</span>
                <span class="text-xs text-text-tertiary">品种: {{ getClientSymbols(client) }}</span>
              </div>
              <div class="mt-1 text-xs text-text-tertiary space-x-3">
                <span v-if="client.username">所属用户: <span class="text-text-secondary">{{ client.username }}</span></span>
                <span v-if="client.account_name">绑定账户: <span class="text-text-secondary">{{ client.account_name }}</span></span>
              </div>
            </div>
            <div @click="toggleMT5Active(client)"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors flex-shrink-0 ml-2',
                client.is_active ? 'bg-[#0ecb81]' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                client.is_active ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
          </div>

          <!-- MT5 账号信息 -->
          <div class="text-xs space-y-1.5">
            <div class="flex justify-between items-center">
              <span class="text-text-tertiary">系统服务:</span>
              <div class="flex items-center gap-2">
                <div @click="toggleSystemService(client)"
                  :class="['relative w-8 h-4 rounded-full cursor-pointer transition-colors',
                    client.is_system_service ? 'bg-purple-500' : 'bg-gray-600']">
                  <span :class="['absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform',
                    client.is_system_service ? 'translate-x-4' : 'translate-x-0.5']"/>
                </div>
                <span class="text-text-tertiary">{{ client.is_system_service ? '仅行情数据' : '完整交易' }}</span>
              </div>
            </div>
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
          </div>

          <!-- Bridge 部署信息 -->
          <div class="bg-dark-200 rounded-lg p-2.5 text-xs">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-text-tertiary font-medium">Bridge 部署</span>
              <div class="flex items-center gap-1.5">
                <span v-if="clientInstances[client.client_id]?.length"
                  class="px-1.5 py-0.5 rounded text-[10px]"
                  :class="getInstanceStatusClass(clientInstances[client.client_id])">
                  {{ getInstanceStatusText(clientInstances[client.client_id]) }}
                </span>
                <span v-else class="px-1.5 py-0.5 rounded text-[10px] bg-dark-300 text-text-tertiary">未部署</span>
                <button @click="openDeployModal(client)"
                  class="px-1.5 py-0.5 bg-dark-50 hover:bg-dark-100 border border-border-primary rounded text-text-secondary transition-colors">
                  {{ clientInstances[client.client_id]?.length ? '管理' : '部署' }}
                </button>
              </div>
            </div>
            <div v-if="clientInstances[client.client_id]?.length" class="space-y-1.5">
              <div v-for="inst in clientInstances[client.client_id]" :key="inst.instance_id"
                class="bg-dark-300 rounded px-2 py-1.5 space-y-1">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-1.5">
                    <div :class="['w-1.5 h-1.5 rounded-full', inst._live_running ? 'bg-[#0ecb81]' : 'bg-gray-500']"></div>
                    <span class="text-text-secondary">{{ inst.instance_name }}</span>
                    <span class="text-text-tertiary">({{ inst.instance_type === 'primary' ? '主' : '备' }})</span>
                  </div>
                  <div class="flex items-center gap-1.5">
                    <span class="font-mono text-text-tertiary">:{{ inst.service_port }}</span>
                    <span :class="inst._live_running ? 'text-[#0ecb81]' : 'text-[#f6465d]'">{{ inst._live_running ? '运行中' : '已停止' }}</span>
                  </div>
                </div>
                <!-- 远程控制按钮 -->
                <div class="flex gap-1">
                  <button v-if="!inst._live_running" @click="controlInstance(inst, 'start')"
                    class="flex-1 py-0.5 bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] rounded text-[10px] transition-colors">启动</button>
                  <button v-else @click="controlInstance(inst, 'stop')"
                    class="flex-1 py-0.5 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded text-[10px] transition-colors">停止</button>
                  <button @click="controlInstance(inst, 'restart')"
                    class="flex-1 py-0.5 bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] rounded text-[10px] transition-colors">重启</button>
                </div>
              </div>
            </div>
            <div v-else class="text-text-tertiary text-center py-1">未部署 Bridge 实例</div>
          </div>

          <!-- MT5 终端控制（RDP 会话层） -->
          <div v-if="clientTerminals[client.client_id]" class="bg-dark-200 rounded-lg p-2.5 text-xs">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-text-tertiary font-medium">MT5 终端进程</span>
              <span class="text-text-tertiary text-[10px]">RDP 会话层</span>
            </div>
            <div v-for="term in clientTerminals[client.client_id]" :key="term.instance_name"
              class="bg-dark-300 rounded px-2 py-1.5 space-y-1">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <div :class="['w-1.5 h-1.5 rounded-full', term.is_running ? 'bg-[#0ecb81]' : 'bg-gray-500']"></div>
                  <span class="text-text-secondary">{{ term.display_name || term.instance_name }}</span>
                </div>
                <div class="flex items-center gap-1.5">
                  <span v-if="term.health_status?.details?.pid" class="font-mono text-text-tertiary">PID:{{ term.health_status.details.pid }}</span>
                  <span v-if="term.health_status?.details?.memory_mb" class="text-text-tertiary">{{ term.health_status.details.memory_mb.toFixed(0) }}MB</span>
                  <span :class="term.is_running ? 'text-[#0ecb81]' : 'text-[#f6465d]'">{{ term.is_running ? '运行' : '停止' }}</span>
                </div>
              </div>
              <div class="flex gap-1">
                <button v-if="!term.is_running" @click="controlTerminal(term.instance_name, 'start')"
                  class="flex-1 py-0.5 bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] rounded text-[10px] transition-colors">启动终端</button>
                <button v-else @click="controlTerminal(term.instance_name, 'stop')"
                  class="flex-1 py-0.5 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded text-[10px] transition-colors">停止终端</button>
                <button @click="controlTerminal(term.instance_name, 'restart')"
                  class="flex-1 py-0.5 bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] rounded text-[10px] transition-colors">重启终端</button>
              </div>
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
            <button @click="checkClientHealth(client)"
              class="flex-1 py-1.5 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 rounded-lg text-xs border border-blue-500/20 transition-colors">
              健康检查
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

    <!-- ══════════════════════════════════════
         Modal: 新增/编辑用户
    ════════════════════════════════════════ -->
    <div v-if="showUserModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      >
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">{{ isEditUser ? '编辑用户' : '新增用户' }}</h3>
          <button @click="showUserModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="saveUser" autocomplete="off" class="p-6 space-y-4">
          <!-- Hidden dummy fields to prevent browser autofill -->
          <input type="text" name="prevent_autofill" style="display:none" />
          <input type="password" name="prevent_autofill_pw" style="display:none" />
          <div>
            <label class="block text-xs text-text-tertiary mb-1">用户名 *</label>
            <input v-model="userForm.username" required :disabled="isEditUser"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary disabled:opacity-50"
              placeholder="输入用户名" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">邮箱</label>
            <input v-model="userForm.email" type="email" autocomplete="off"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              placeholder="输入邮箱（可选）" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">
              {{ isEditUser ? '密码（留空表示不修改）' : '密码 *' }}
            </label>
            <div class="relative">
              <input v-model="userForm.password" :type="secretVisible.user_password ? 'text' : 'password'" :required="!isEditUser" autocomplete="new-password"
                class="w-full px-3 py-2 pr-16 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
                :placeholder="isEditUser ? '留空表示不修改' : '至少8个字符'" />
              <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                <span v-if="isEditUser && !userForm.password" class="text-[10px] text-green-500">已设置</span>
                <button type="button" v-if="userForm.password" @click="secretVisible.user_password = !secretVisible.user_password"
                  class="text-text-tertiary hover:text-text-primary text-xs px-1" :title="secretVisible.user_password ? '隐藏' : '查看'">
                  {{ secretVisible.user_password ? '🙈' : '👁' }}
                </button>
              </div>
            </div>
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
              <div class="flex gap-2">
                <input v-model="userForm.feishu_mobile" type="tel" autocomplete="off"
                  class="flex-1 px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
                  placeholder="绑定手机号（留空不修改）" />
                <button type="button" @click="lookupFeishuId"
                  :disabled="feishuLookupLoading || !userForm.feishu_mobile"
                  class="px-3 py-2 bg-[#3370ff] hover:bg-[#2860e6] text-white rounded-lg text-xs font-medium whitespace-nowrap transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                  {{ feishuLookupLoading ? '查询中...' : '获取飞书ID' }}
                </button>
              </div>
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
      >
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
      >
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">{{ isEditAccount ? '编辑账户' : '新增账户' }}</h3>
          <button @click="showAccountModal = false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <form @submit.prevent="saveAccount" class="p-6 space-y-4">
          <!-- 所属用户（新增和编辑时都显示） -->
          <div>
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
              <option v-for="p in platforms" :key="p.platform_id" :value="p.platform_id">
                {{ p.display_name || p.platform_name }}
              </option>
            </select>
          </div>
          <div v-if="platformSupportsMT5(accountForm.platform_id)" class="flex items-center gap-3">
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
            <div class="relative">
              <input v-model="accountForm.api_secret" :type="secretVisible.api_secret ? 'text' : 'password'" :required="!isEditAccount" autocomplete="new-password"
                class="w-full px-3 py-2 pr-16 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                :placeholder="isEditAccount && secretHasData.api_secret ? '••••••••（已设置）' : '输入 API Secret'" />
              <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                <span v-if="isEditAccount && secretHasData.api_secret && !accountForm.api_secret" class="text-[10px] text-green-500">已设置</span>
                <button type="button" v-if="accountForm.api_secret" @click="secretVisible.api_secret = !secretVisible.api_secret"
                  class="text-text-tertiary hover:text-text-primary text-xs px-1" :title="secretVisible.api_secret ? '隐藏' : '查看'">
                  {{ secretVisible.api_secret ? '🙈' : '👁' }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="accountForm.platform_id !== 1">
            <label class="block text-xs text-text-tertiary mb-1">{{ accountForm.platform_id === 5 ? 'Passphrase *' : 'Passphrase（可选）' }}</label>
            <div class="relative">
              <input v-model="accountForm.passphrase" :type="secretVisible.passphrase ? 'text' : 'password'" :required="accountForm.platform_id === 5"
                class="w-full px-3 py-2 pr-16 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                :placeholder="isEditAccount && secretHasData.passphrase ? '••••••••（已设置）' : (accountForm.platform_id === 5 ? 'OKX API Passphrase（必填）' : 'API Passphrase')" />
              <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                <span v-if="isEditAccount && secretHasData.passphrase && !accountForm.passphrase" class="text-[10px] text-green-500">已设置</span>
                <button type="button" v-if="accountForm.passphrase" @click="secretVisible.passphrase = !secretVisible.passphrase"
                  class="text-text-tertiary hover:text-text-primary text-xs px-1" :title="secretVisible.passphrase ? '隐藏' : '查看'">
                  {{ secretVisible.passphrase ? '🙈' : '👁' }}
                </button>
              </div>
            </div>
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">杠杆倍数</label>
            <input v-model.number="accountForm.leverage" type="number" min="1" max="1000"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
              :placeholder="`默认 ${defaultLeverage(accountForm.platform_id)}x`" />
          </div>
          <div>
            <label class="block text-xs text-text-tertiary mb-1">
              账户角色
              <span class="text-text-tertiary ml-1 normal-case font-normal">（每用户1个主账号；每平台1个对冲账户）</span>
            </label>
            <select v-model="accountForm.account_role"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="">-- 无角色 --</option>
              <option value="primary">主账号（primary）</option>
              <option value="hedge">对冲账号（hedge）</option>
            </select>
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
      >
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
            <div class="relative">
              <input v-model="mt5Form.mt5_password" :type="secretVisible.mt5_password ? 'text' : 'password'" :required="!isEditMT5"
                autocomplete="new-password"
                class="w-full px-3 py-2 pr-16 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                :placeholder="isEditMT5 && secretHasData.mt5_password ? '••••••••（已设置）' : '输入MT5登录密码'" />
              <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                <span v-if="isEditMT5 && secretHasData.mt5_password && !mt5Form.mt5_password" class="text-[10px] text-green-500">已设置</span>
                <button type="button" v-if="mt5Form.mt5_password" @click="secretVisible.mt5_password = !secretVisible.mt5_password"
                  class="text-text-tertiary hover:text-text-primary text-xs px-1" :title="secretVisible.mt5_password ? '隐藏' : '查看'">
                  {{ secretVisible.mt5_password ? '🙈' : '👁' }}
                </button>
              </div>
            </div>
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
            <!-- bridge_url 由系统自动管理 -->

          <div class="flex items-center gap-3">
            <div @click="mt5Form.is_system_service = !mt5Form.is_system_service"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                mt5Form.is_system_service ? 'bg-purple-500' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                mt5Form.is_system_service ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
            <span class="text-sm text-text-secondary">系统服务（仅行情/点差数据，不参与交易）</span>
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

    <!-- Modal: IPIPGO 静态IP代理配置 -->
    <div v-if="showProxyModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      >
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
              <div class="relative">
                <input v-model="proxyForm.password" :type="secretVisible.proxy_password ? 'text' : 'password'"
                  class="w-full px-3 py-2 pr-16 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                  :placeholder="secretHasData.proxy_password && !proxyForm.password ? '••••••••（已设置）' : 'IPIPGO 密码'" />
                <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <span v-if="secretHasData.proxy_password && !proxyForm.password" class="text-[10px] text-green-500">已设置</span>
                  <button type="button" v-if="proxyForm.password" @click="secretVisible.proxy_password = !secretVisible.proxy_password"
                    class="text-text-tertiary hover:text-text-primary text-xs px-1" :title="secretVisible.proxy_password ? '隐藏' : '查看'">
                    {{ secretVisible.proxy_password ? '🙈' : '👁' }}
                  </button>
                </div>
              </div>
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

    <!-- Modal: Bridge 部署管理 -->
    <div v-if="showDeployModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      >
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-xl max-h-[90vh] flex flex-col">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between flex-shrink-0">
          <div>
            <h3 class="font-bold">Bridge 部署管理 — {{ deployClient?.client_name }}</h3>
            <p class="text-xs text-text-tertiary mt-0.5">MT5 Login: {{ deployClient?.mt5_login }} | 品种: {{ deployForm.symbols.length ? deployForm.symbols.join(', ') : '未选择' }}</p>
          </div>
          <button @click="showDeployModal = false" class="text-text-tertiary hover:text-text-primary text-lg">&#x2715;</button>
        </div>
        <div class="p-6 space-y-4 overflow-y-auto flex-1">
          <!-- 部署/删除进度面板 -->
          <div v-if="deployProgress.active" class="bg-dark-200 rounded-xl p-4 space-y-3">
            <div class="flex items-center gap-2">
              <svg v-if="!deployProgress.done" class="w-4 h-4 animate-spin text-primary" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              <span class="text-sm font-semibold" :class="deployProgress.error ? 'text-[#f6465d]' : deployProgress.done ? 'text-[#0ecb81]' : 'text-primary'">
                {{ deployProgress.title }}
              </span>
            </div>
            <!-- 进度条 -->
            <div class="w-full bg-dark-300 rounded-full h-2">
              <div class="h-2 rounded-full transition-all duration-500"
                :class="deployProgress.error ? 'bg-[#f6465d]' : 'bg-primary'"
                :style="{ width: deployProgress.percent + '%' }"></div>
            </div>
            <!-- 步骤列表 -->
            <div class="space-y-1">
              <div v-for="(step, i) in deployProgress.steps" :key="i" class="flex items-center gap-2 text-xs">
                <span v-if="step.status === 'done'" class="text-[#0ecb81]">&#x2713;</span>
                <span v-else-if="step.status === 'error'" class="text-[#f6465d]">&#x2717;</span>
                <span v-else-if="step.status === 'running'" class="text-primary animate-pulse">&#x25CF;</span>
                <span v-else class="text-text-tertiary">&#x25CB;</span>
                <span :class="step.status === 'done' ? 'text-text-secondary' : step.status === 'error' ? 'text-[#f6465d]' : step.status === 'running' ? 'text-text-primary' : 'text-text-tertiary'">
                  {{ step.label }}
                </span>
              </div>
            </div>
            <button v-if="deployProgress.done || deployProgress.error" @click="deployProgress.active = false"
              class="w-full py-1.5 bg-dark-300 hover:bg-dark-50 text-text-secondary rounded-lg text-xs transition-colors">
              关闭
            </button>
          </div>

          <!-- 已有实例列表 -->
          <div v-if="deployInstances.length" class="space-y-2">
            <div class="text-xs font-semibold text-text-tertiary uppercase tracking-wide">已部署实例</div>
            <div v-for="inst in deployInstances" :key="inst.instance_id"
              class="bg-dark-200 rounded-lg p-3 space-y-2">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <div :class="['w-2 h-2 rounded-full', inst.status === 'running' ? 'bg-[#0ecb81]' : 'bg-gray-500']"></div>
                  <span class="font-medium text-sm">{{ inst.instance_name }}</span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-dark-300 text-text-tertiary">{{ inst.instance_type === 'primary' ? '主实例' : '备用实例' }}</span>
                </div>
                <span :class="inst.status === 'running' ? 'text-[#0ecb81]' : 'text-text-tertiary'" class="text-xs">{{ inst.status }}</span>
              </div>
              <div class="text-xs text-text-tertiary grid grid-cols-2 gap-1">
                <div>IP: <span class="text-text-secondary font-mono">{{ inst.server_ip }}</span></div>
                <div>端口: <span class="text-text-secondary font-mono">{{ inst.service_port }}</span></div>
                <div>MT5路径: <span class="text-text-secondary font-mono truncate" :title="inst.mt5_path">{{ inst.mt5_path }}</span></div>
                <div>部署路径: <span class="text-text-secondary font-mono truncate" :title="inst.deploy_path">{{ inst.deploy_path }}</span></div>
              </div>
              <div class="flex gap-2">
                <button @click="editDeployInstance(inst)"
                  class="px-2 py-1 bg-dark-300 hover:bg-dark-50 text-text-secondary rounded text-xs transition-colors">编辑</button>
                <button @click="deleteDeployInstance(inst)"
                  class="px-2 py-1 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded text-xs transition-colors">删除</button>
              </div>
            </div>
          </div>

          <!-- 新建/编辑部署表单 -->
          <div class="border-t border-border-secondary pt-3 space-y-3">
            <div class="text-xs font-semibold text-text-tertiary uppercase tracking-wide">
              {{ isEditDeploy ? '编辑实例' : '新建 Bridge 实例' }}
            </div>
            <div class="grid grid-cols-2 gap-3">
              <!-- MT5 登录凭证（自动从客户端记录读取，只读展示） -->
              <div class="col-span-2 bg-dark-200/50 rounded-lg p-3 space-y-1.5 border border-border-primary/50">
                <div class="text-xs font-semibold text-text-tertiary">MT5 登录凭证（自动从账户读取，部署时自动配置）</div>
                <div class="grid grid-cols-3 gap-2 text-xs">
                  <div>登录号: <span class="text-text-primary font-mono font-medium">{{ deployClient?.mt5_login || '-' }}</span></div>
                  <div>服务器: <span class="text-text-primary font-mono font-medium">{{ deployClient?.mt5_server || '-' }}</span></div>
                  <div>密码: <span class="text-text-primary">{{ deployClient?.password_type === 'primary' ? '主密码 ●●●●' : '只读密码 ●●●●' }}</span></div>
                </div>
              </div>
              <!-- 交易品种选择（从 hedging pairs 获取该平台可用的 MT5 symbols） -->
              <div class="col-span-2">
                <label class="block text-xs text-text-tertiary mb-1.5">交易品种 *</label>
                <div class="flex flex-wrap gap-1.5">
                  <button v-for="sym in availableDeploySymbols" :key="sym" type="button"
                    @click="toggleDeploySymbol(sym)"
                    :class="['px-2.5 py-1 rounded-lg text-xs font-mono transition-colors border',
                      deployForm.symbols.includes(sym)
                        ? 'bg-primary/20 text-primary border-primary/40'
                        : 'bg-dark-200 text-text-tertiary border-border-primary hover:text-text-secondary']">
                    {{ sym }}
                  </button>
                  <button v-if="availableDeploySymbols.length > 1" type="button" @click="toggleAllDeploySymbols"
                    class="px-2.5 py-1 rounded-lg text-xs transition-colors border bg-dark-200 text-text-secondary border-border-primary hover:bg-dark-50">
                    {{ deployForm.symbols.length === availableDeploySymbols.length ? '取消全选' : '全选' }}
                  </button>
                </div>
                <p v-if="!availableDeploySymbols.length" class="text-xs text-text-tertiary mt-1">该平台暂无可用品种</p>
              </div>
              <div class="col-span-2">
                <label class="block text-xs text-text-tertiary mb-1">实例名称 *</label>
                <input v-model="deployForm.instance_name" required
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary"
                  :placeholder="`${deployClient?.client_name}-实例`" />
              </div>
              <div>
                <label class="block text-xs text-text-tertiary mb-1">服务器 IP *</label>
                <input v-model="deployForm.server_ip" required
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                  placeholder="172.31.14.113" />
              </div>
              <div>
                <label class="block text-xs text-text-tertiary mb-1">服务端口 *</label>
                <input v-model.number="deployForm.service_port" type="number" required min="1024" max="65535"
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                  placeholder="8003" />
              </div>
              <div class="col-span-2">
                <label class="block text-xs text-text-tertiary mb-1">MT5 安装路径 *</label>
                <input v-model="deployForm.mt5_path" required
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                  placeholder="D:\MetaTrader 5-01\terminal64.exe" />
              </div>
              <div class="col-span-2">
                <label class="block text-xs text-text-tertiary mb-1">MT5 数据目录</label>
                <input v-model="deployForm.mt5_data_path"
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                  placeholder="D:\MetaTrader 5-01（可选）" />
              </div>
              <div class="col-span-2">
                <label class="block text-xs text-text-tertiary mb-1">Bridge 部署路径 *</label>
                <input v-model="deployForm.deploy_path" required
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm font-mono focus:outline-none focus:border-primary"
                  placeholder="D:\hustle-mt5-xxx" />
              </div>
              <div>
                <label class="block text-xs text-text-tertiary mb-1">实例类型 *</label>
                <select v-model="deployForm.instance_type"
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
                  <option value="primary">主实例 (Primary)</option>
                  <option value="backup">备用实例 (Backup)</option>
                </select>
              </div>
              <div class="flex items-end">
                <div class="flex items-center gap-3 py-2">
                  <div @click="deployForm.auto_start = !deployForm.auto_start"
                    :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors',
                      deployForm.auto_start ? 'bg-[#0ecb81]' : 'bg-gray-600']">
                    <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
                      deployForm.auto_start ? 'translate-x-4' : 'translate-x-0.5']"/>
                  </div>
                  <span class="text-sm text-text-secondary">开机自启</span>
                </div>
              </div>
            </div>
            <div class="flex gap-3">
              <button @click="saveDeploy"
                class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors">
                {{ isEditDeploy ? '保存修改' : '部署实例' }}
              </button>
              <button v-if="isEditDeploy" @click="resetDeployForm"
                class="py-2 px-4 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
                取消编辑
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: 通知订阅分配 -->
    <div v-if="showNotifModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      >
      <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between flex-shrink-0">
          <div>
            <h3 class="font-bold">通知订阅分配 — {{ notifUser?.username }}</h3>
            <p class="text-xs text-text-tertiary mt-0.5">选择要接收哪些交易员账号的哪些通知</p>
          </div>
          <button @click="showNotifModal = false" class="text-text-tertiary hover:text-text-primary text-lg">&#x2715;</button>
        </div>
        <div class="p-6 space-y-4 overflow-y-auto flex-1">
          <div v-if="notifLoading" class="text-center py-8 text-text-tertiary text-sm">加载中...</div>
          <div v-else-if="!notifTemplates.length" class="text-center py-8 text-text-tertiary text-sm">暂无启用的通知模板</div>
          <template v-else>
            <!-- 按交易员分组 -->
            <div v-for="trader in notifTraders" :key="trader.user_id" class="space-y-2">
              <div class="flex items-center gap-2 px-1">
                <span class="text-sm font-semibold text-text-primary">{{ trader.username }}</span>
                <span class="text-xs text-text-tertiary">({{ trader.role || '交易员' }})</span>
                <button type="button" @click="toggleAllForTrader(trader.user_id, true)"
                  class="ml-auto text-xs text-primary hover:underline">全选</button>
                <button type="button" @click="toggleAllForTrader(trader.user_id, false)"
                  class="text-xs text-text-tertiary hover:underline">全不选</button>
              </div>
              <!-- 按分类分组模板 -->
              <div v-for="cat in notifCategories" :key="cat"
                class="bg-dark-200 rounded-lg px-3 py-2">
                <div class="text-xs text-text-tertiary font-medium mb-1.5 uppercase tracking-wide">{{ notifCatLabel(cat) }}</div>
                <div class="flex flex-wrap gap-x-4 gap-y-1">
                  <label v-for="tpl in templatesByCategory(cat)" :key="tpl.template_id"
                    class="flex items-center gap-1.5 cursor-pointer hover:opacity-80 transition-opacity">
                    <input type="checkbox"
                      :checked="isSubscribed(trader.user_id, tpl.template_id)"
                      @change="toggleSub(trader.user_id, tpl.template_id)"
                      class="accent-primary w-3.5 h-3.5" />
                    <span class="text-xs text-text-secondary">{{ tpl.template_name }}</span>
                  </label>
                </div>
              </div>
            </div>

</template>
        </div>
        <div class="px-6 py-4 border-t border-border-secondary flex gap-3 flex-shrink-0">
          <button @click="saveNotifConfig" :disabled="notifLoading"
            class="flex-1 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm transition-colors disabled:opacity-50">
            保存
          </button>
          <button @click="showNotifModal = false"
            class="flex-1 py-2 bg-dark-200 hover:bg-dark-50 text-text-secondary rounded-lg text-sm border border-border-primary transition-colors">
            取消
          </button>
        </div>
      </div>
    </div>

          
    <!-- ════════ 子账号管理 Modal ════════ -->
    <div v-if="subModalOpen" @click.self="closeSubModal"
         class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div class="bg-dark-100 rounded-xl border border-border-primary p-5 w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-bold">子账号管理 — 父账号 <span class="text-primary">{{ subParent?.username }}</span></h3>
          <button @click="closeSubModal" class="text-text-tertiary hover:text-text-primary text-lg">×</button>
        </div>
        <div class="text-xs text-text-tertiary mb-4">
          子账号按"基金份额"模型登录 www.hustle2026.xyz 查看父账号资产；不可下单 / 划转 / 修改账户 / 查看资金流向。
          创建时填写人民币投入，系统按当下汇率折算 USDT 并锁定份额。
        </div>

        <!-- 现有子账号列表 -->
        <div class="bg-dark-200 rounded-lg p-3 border border-border-primary mb-4">
          <div class="flex items-center justify-between mb-2">
            <span class="font-medium text-sm">已创建子账号</span>
            <button @click="reloadSubs" class="text-xs text-text-tertiary hover:text-primary">🔄 刷新</button>
          </div>
          <div v-if="subListLoading" class="text-center py-4 text-xs text-text-tertiary">加载中…</div>
          <div v-else-if="!subList.length" class="text-center py-4 text-xs text-text-tertiary">暂无子账号</div>
          <table v-else class="w-full text-xs">
            <thead class="text-text-tertiary border-b border-border-primary">
              <tr>
                <th class="text-left py-1.5">用户名</th>
                <th class="text-right py-1.5">投入(¥)</th>
                <th class="text-right py-1.5">折合(USDT)</th>
                <th class="text-right py-1.5">份额</th>
                <th class="text-right py-1.5">当前估值(USDT)</th>
                <th class="text-right py-1.5">占比</th>
                <th class="text-center py-1.5">状态</th>
                <th class="text-center py-1.5">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="row in subList" :key="row.id">
              <tr class="border-b border-border-secondary/50">
                <td class="py-1.5 font-mono text-text-primary">{{ row.sub_username }}</td>
                <td class="py-1.5 text-right font-mono">{{ Number(row.invested_cny).toLocaleString() }}</td>
                <td class="py-1.5 text-right font-mono">{{ Number(row.invested_usdt).toFixed(2) }}</td>
                <td class="py-1.5 text-right font-mono">{{ Number(row.shares).toFixed(4) }}</td>
                <td class="py-1.5 text-right font-mono"
                  :class="row.sub_current_value_usdt >= row.invested_usdt ? 'text-success' : 'text-danger'">
                  {{ Number(row.sub_current_value_usdt).toFixed(2) }}
                </td>
                <td class="py-1.5 text-right font-mono">{{ ((row.multiplier || 0) * 100).toFixed(2) }}%</td>
                <td class="py-1.5 text-center">
                  <span :class="row.status === 'active' ? 'text-success' : 'text-text-tertiary'"
                    class="text-[10px] px-1.5 py-0.5 rounded"
                    :style="row.status === 'active' ? 'background:rgba(14,203,129,0.1)' : 'background:rgba(255,255,255,0.05)'">
                    {{ row.status === 'active' ? '启用' : '停用' }}
                  </span>
                </td>
                <td class="py-1.5 text-center space-x-1">
                  <button @click.stop="startEditSub(row)"
                    class="text-[10px] text-primary hover:opacity-80">编辑</button>
                  <button v-if="row.status === 'active'" @click.stop="deactivateSub(row)"
                    class="text-[10px] text-danger hover:opacity-80">停用</button>
                  <button v-if="row.status !== 'active'" @click.stop="reactivateSub(row)"
                    class="text-[10px] text-success hover:opacity-80">启用</button>
                </td>
              </tr>
              <!-- Inline edit row -->
              <tr v-if="editingSub && editingSub.id === row.id" class="bg-dark-100/50">
                <td colspan="8" class="py-3 px-3">
                  <div class="space-y-2">
                    <div class="grid grid-cols-4 gap-2 text-[10px] bg-dark-200/50 rounded p-2">
                      <div>
                        <span class="text-text-tertiary">投入(¥)</span>
                        <input v-model.number="editSubForm.invested_cny" type="number" step="100" min="0"
                          class="w-full bg-dark-200 border border-border-primary rounded px-1.5 py-0.5 text-xs font-mono mt-0.5" />
                      </div>
                      <div>
                        <span class="text-text-tertiary">折合(USDT)</span>
                        <input v-model.number="editSubForm.invested_usdt" type="number" step="0.01" min="0"
                          class="w-full bg-dark-200 border border-border-primary rounded px-1.5 py-0.5 text-xs font-mono mt-0.5" />
                      </div>
                      <div>
                        <span class="text-text-tertiary">份额</span>
                        <input v-model.number="editSubForm.shares" type="number" step="0.0001" min="0"
                          class="w-full bg-dark-200 border border-border-primary rounded px-1.5 py-0.5 text-xs font-mono mt-0.5" />
                      </div>
                      <div>
                        <span class="text-text-tertiary">当前估值</span>
                        <div class="font-mono text-xs mt-1" :class="row.sub_current_value_usdt >= row.invested_usdt ? 'text-success' : 'text-danger'">
                          {{ Number(row.sub_current_value_usdt).toFixed(2) }} USDT
                        </div>
                      </div>
                    </div>
                    <div class="flex items-center gap-3 flex-wrap">
                      <div class="flex items-center gap-1">
                        <span class="text-[10px] text-text-tertiary">用户名:</span>
                        <span class="text-xs font-mono text-text-primary">{{ row.sub_username }}</span>
                      </div>
                      <div class="flex items-center gap-1">
                        <span class="text-[10px] text-text-tertiary">新密码:</span>
                        <div class="relative">
                          <input v-model="editSubForm.password" :type="editSubForm.showPw ? 'text' : 'password'"
                            placeholder="留空不修改" autocomplete="new-password"
                            class="bg-dark-200 border border-border-primary rounded px-2 py-1 text-xs font-mono w-36 pr-8" />
                          <button type="button" v-if="editSubForm.password" @click="editSubForm.showPw = !editSubForm.showPw"
                            class="absolute right-1.5 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary text-[10px]">
                            {{ editSubForm.showPw ? '🙈' : '👁' }}
                          </button>
                        </div>
                      </div>
                      <div class="flex items-center gap-1">
                        <span class="text-[10px] text-text-tertiary">状态:</span>
                        <select v-model="editSubForm.is_active"
                          class="bg-dark-200 border border-border-primary rounded px-1.5 py-1 text-[10px]">
                          <option :value="true">启用</option>
                          <option :value="false">停用</option>
                        </select>
                      </div>
                      <button @click="saveEditSub" :disabled="editSubSaving"
                        class="px-2.5 py-1 bg-primary hover:bg-primary-hover text-dark-300 rounded text-[10px] font-medium disabled:opacity-50">
                        {{ editSubSaving ? '保存中…' : '保存' }}
                      </button>
                      <button @click="editingSub = null" class="px-2 py-1 text-[10px] text-text-tertiary hover:text-text-primary">取消</button>
                    </div>
                  </div>
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- 父账号入金/出金登记 -->
        <div class="bg-dark-200 rounded-lg p-3 border border-border-primary mb-4">
          <div class="flex items-center justify-between mb-2">
            <span class="font-medium text-sm">父账号入金 / 出金登记</span>
            <button @click="reloadCashflow" class="text-xs text-text-tertiary hover:text-primary">🔄 刷新</button>
          </div>
          <div class="text-[10px] text-text-tertiary mb-3">
            父账号注资 / 提取时必须在此登记，系统按当下 NAV 铸造 / 销毁虚拟份额，使子账号估值不受影响。
            份额状态：当前虚拟份额 <span class="font-mono text-primary">{{ cashflowState.virtual_shares != null ? Number(cashflowState.virtual_shares).toFixed(4) : '--' }}</span>
            · 基准初始资产 <span class="font-mono">{{ cashflowState.bootstrap_total_assets != null ? Number(cashflowState.bootstrap_total_assets).toFixed(2) + ' USDT' : '--' }}</span>
          </div>
          <div class="grid grid-cols-3 gap-2 mb-2">
            <select v-model="cashForm.direction" class="bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-xs">
              <option value="deposit">入金 +</option>
              <option value="withdraw">出金 -</option>
            </select>
            <input v-model.number="cashForm.amount_usdt" type="number" min="0.01" step="0.01" placeholder="金额(USDT)"
              class="bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-xs font-mono" />
            <input v-model="cashForm.note" placeholder="备注(可选)"
              class="bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-xs" />
          </div>
          <div class="flex justify-end mb-3">
            <button @click="submitCashflow" :disabled="cashSubmitting"
              class="px-3 py-1.5 bg-[#f0b90b]/80 hover:bg-[#f0b90b] text-dark-300 rounded-lg text-xs font-medium disabled:opacity-50">
              {{ cashSubmitting ? '登记中…' : '登记并重算份额' }}
            </button>
          </div>
          <div v-if="cashEvents.length" class="max-h-44 overflow-y-auto">
            <table class="w-full text-[10px]">
              <thead class="text-text-tertiary border-b border-border-primary">
                <tr>
                  <th class="text-left py-1">时间</th>
                  <th class="text-center py-1">方向</th>
                  <th class="text-right py-1">金额(USDT)</th>
                  <th class="text-right py-1">NAV</th>
                  <th class="text-right py-1">Δ份额</th>
                  <th class="text-left py-1 pl-2">备注</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="ev in cashEvents" :key="ev.id" class="border-b border-border-secondary/30">
                  <td class="py-1 text-text-tertiary">{{ fmtDate(ev.created_at) }}</td>
                  <td class="py-1 text-center" :class="ev.direction === 'deposit' ? 'text-success' : 'text-danger'">
                    {{ ev.direction === 'deposit' ? '入金' : '出金' }}
                  </td>
                  <td class="py-1 text-right font-mono">{{ Number(ev.amount_usdt).toFixed(2) }}</td>
                  <td class="py-1 text-right font-mono text-text-tertiary">{{ Number(ev.nav_at_event).toFixed(4) }}</td>
                  <td class="py-1 text-right font-mono"
                    :class="ev.shares_delta >= 0 ? 'text-success' : 'text-danger'">
                    {{ ev.shares_delta > 0 ? '+' : '' }}{{ Number(ev.shares_delta).toFixed(4) }}
                  </td>
                  <td class="py-1 pl-2 text-text-secondary truncate max-w-[120px]">{{ ev.note || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="text-center py-3 text-[10px] text-text-tertiary">暂无入金/出金记录</div>
        </div>

        <!-- 新增 -->
        <div class="bg-dark-200 rounded-lg p-3 border border-border-primary">
          <div class="font-medium text-sm mb-3">+ 新增子账号</div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="text-xs text-text-tertiary">用户名</label>
              <input v-model="subForm.username" placeholder="如 sub_alice" autocomplete="off"
                class="w-full bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-sm" />
            </div>
            <div>
              <label class="text-xs text-text-tertiary">登录密码</label>
              <div class="relative">
                <input v-model="subForm.password" :type="secretVisible.sub_password ? 'text' : 'password'" placeholder="至少 6 位" autocomplete="new-password"
                  class="w-full bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-sm pr-10" />
                <button type="button" v-if="subForm.password" @click="secretVisible.sub_password = !secretVisible.sub_password"
                  class="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary text-xs px-1">
                  {{ secretVisible.sub_password ? '🙈' : '👁' }}
                </button>
              </div>
            </div>
            <div>
              <label class="text-xs text-text-tertiary">投入金额（人民币 ¥）</label>
              <input v-model.number="subForm.invested_cny" type="number" min="100" step="100" placeholder="如 10000"
                class="w-full bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-sm" />
            </div>
            <div>
              <label class="text-xs text-text-tertiary">汇率覆盖（CNY/USDT，留空自动取实时）</label>
              <input v-model.number="subForm.fx_override" type="number" step="0.01" placeholder="自动"
                class="w-full bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-sm" />
            </div>
          </div>
          <div class="text-[10px] text-text-tertiary mt-2">
            汇率优先级：手动覆盖 → OKX/Binance C2C 实时 → 缓存 → 7.20 兜底。一旦创建则永久冻结。
          </div>
          <div class="flex justify-end gap-2 mt-3">
            <button @click="closeSubModal" class="px-3 py-1.5 bg-dark-100 rounded-lg text-xs">关闭</button>
            <button @click="createSub" :disabled="subCreating"
              class="px-3 py-1.5 bg-primary text-dark-300 rounded-lg text-xs font-medium disabled:opacity-50">
              {{ subCreating ? '创建中…' : '创建子账号' }}
            </button>
          </div>
        </div>

        <!-- M2M: 订阅已有子账号 -->
        <div class="bg-dark-200 rounded-lg p-3 border border-border-primary mt-3">
          <div class="font-medium text-sm mb-2">订阅已有子账号 <span class="text-[10px] text-text-tertiary">(多父账号 M2M)</span></div>
          <div class="text-[10px] text-text-tertiary mb-2">
            将一个已经是"子账号"身份的用户再订阅一份到本父账号。系统按当前 NAV 铸造份额并自动把最大份额的父账号设为主父账号（WS 主视图）。
          </div>
          <div class="grid grid-cols-3 gap-2">
            <input v-model="m2mForm.sub_username" placeholder="已存在的子账号用户名"
              class="bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-xs" />
            <input v-model.number="m2mForm.invested_cny" type="number" min="100" step="100" placeholder="投入 ¥CNY"
              class="bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-xs font-mono" />
            <input v-model.number="m2mForm.fx_override" type="number" step="0.01" placeholder="汇率覆盖(可选)"
              class="bg-dark-100 border border-border-primary rounded px-2 py-1.5 text-xs font-mono" />
          </div>
          <div class="flex justify-end mt-2">
            <button @click="subscribeExistingSub" :disabled="m2mSubmitting"
              class="px-3 py-1.5 bg-purple-500/80 hover:bg-purple-500 text-white rounded-lg text-xs font-medium disabled:opacity-50">
              {{ m2mSubmitting ? '订阅中…' : '订阅到本父账号' }}
            </button>
          </div>
        </div>
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

    <!-- Modal: 对冲倍数权限 -->
    <Teleport to="body">
      <div v-if="showHedgeModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" @click.self="showHedgeModal = false">
        <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-sm shadow-2xl">
          <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
            <h3 class="font-bold">对冲倍数权限 — {{ hedgeUser?.username }}</h3>
            <button @click="showHedgeModal = false" class="text-text-tertiary hover:text-text-primary text-xl">✕</button>
          </div>
          <div class="p-6 text-center">
            <div class="text-sm text-text-secondary mb-4">是否允许该用户在交易界面调节对冲倍数？</div>
            <div class="flex items-center justify-center gap-3 mb-4">
              <span class="text-sm" :class="!hedgeEnabled ? 'text-text-primary font-bold' : 'text-text-tertiary'">禁用</span>
              <div @click="hedgeEnabled = !hedgeEnabled"
                :class="['relative w-12 h-6 rounded-full cursor-pointer transition-colors', hedgeEnabled ? 'bg-primary' : 'bg-gray-600']">
                <span :class="['absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform', hedgeEnabled ? 'translate-x-6' : 'translate-x-0.5']"/>
              </div>
              <span class="text-sm" :class="hedgeEnabled ? 'text-primary font-bold' : 'text-text-tertiary'">启用</span>
            </div>
            <div class="text-xs text-text-tertiary mb-5">启用后用户可在 go 站策略面板中选择 1.0x~1.5x 对冲倍数</div>
            <div class="flex gap-3">
              <button @click="showHedgeModal = false" class="flex-1 px-4 py-2 text-sm text-text-secondary hover:text-text-primary bg-dark-200 rounded-xl">取消</button>
              <button @click="saveHedgeToggle" :disabled="hedgeSaving"
                class="flex-1 px-4 py-2 text-sm font-bold bg-primary hover:bg-primary-hover text-dark-300 rounded-xl disabled:opacity-50">
                {{ hedgeSaving ? '保存中...' : '保存' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Modal: 产品对账户绑定 -->
    <Teleport to="body">
      <div v-if="showPairBindModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" @click.self="showPairBindModal = false">
        <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-lg shadow-2xl">
          <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
            <div>
              <h3 class="font-bold">产品对绑定 — {{ pairBindAccount?.account_name }}</h3>
              <p class="text-xs text-text-tertiary mt-0.5">设置该账户在哪些产品对中作为主账号(A)或对冲账号(B)</p>
            </div>
            <button @click="showPairBindModal = false" class="text-text-tertiary hover:text-text-primary text-xl">✕</button>
          </div>
          <div class="p-4 space-y-2 max-h-[60vh] overflow-y-auto">
            <div v-for="pair in activePairs" :key="pair.pair_code"
              class="flex items-center justify-between bg-dark-200 rounded-xl px-4 py-3">
              <div>
                <span class="font-bold text-sm">{{ pair.pair_code }}</span>
                <span class="text-xs text-text-tertiary ml-2">{{ pair.symbol_a?.symbol || '' }} / {{ pair.symbol_b?.symbol || '' }}</span>
              </div>
              <div class="flex gap-2">
                <button @click="setPairBind(pair.pair_code, 'A')"
                  :class="['px-3 py-1.5 rounded-lg text-xs font-bold border-2 transition-all',
                    isPairBound(pair.pair_code, 'A') ? 'bg-[#0ecb81] text-dark-300 border-[#0ecb81]' : 'bg-dark-100 text-text-secondary border-border-primary hover:border-[#0ecb81]']">
                  A侧(主)
                </button>
                <button @click="setPairBind(pair.pair_code, 'B')"
                  :class="['px-3 py-1.5 rounded-lg text-xs font-bold border-2 transition-all',
                    isPairBound(pair.pair_code, 'B') ? 'bg-[#f0b90b] text-dark-300 border-[#f0b90b]' : 'bg-dark-100 text-text-secondary border-border-primary hover:border-[#f0b90b]']">
                  B侧(对冲)
                </button>
                <button v-if="isPairBound(pair.pair_code, 'A') || isPairBound(pair.pair_code, 'B')"
                  @click="clearPairBind(pair.pair_code)"
                  class="px-2 py-1.5 rounded-lg text-xs text-[#f6465d] hover:bg-[#f6465d]/10 transition-all">
                  ✕
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
    <!-- Modal: 查看资金权限 -->
    <transition name="modal">
      <div v-if="showFundViewModal"
        class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
        @click.self="showFundViewModal = false">
        <div class="bg-dark-100 rounded-xl p-6 w-full max-w-md border border-border-primary">
          <div class="flex items-center justify-between mb-4">
            <h3 class="font-bold">查看资金权限 — {{ fundViewUser?.username }}</h3>
            <button @click="showFundViewModal = false" class="text-text-tertiary hover:text-text-primary">✕</button>
          </div>
          <div class="text-sm text-text-secondary mb-4">是否允许该用户在 <a href="https://www.hustle2026.xyz/fund-flow" target="_blank" class="text-primary">www.hustle2026.xyz/fund-flow</a> 查看资金流向（划转 / 充值 / 提现）记录？</div>
          <label class="flex items-center gap-2 mb-4 text-sm">
            <input type="checkbox" v-model="fundViewEnabled" class="accent-primary">
            <span>授予「资金流向」查看权限</span>
          </label>
          <div class="text-xs text-text-tertiary mb-5">
            启用后该用户可访问 www 站点底部导航的「资金流向」页；未开启时该入口与后端接口都会被屏蔽。
          </div>
          <div class="flex justify-end gap-2">
            <button @click="showFundViewModal = false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">取消</button>
            <button @click="saveFundViewToggle" :disabled="fundViewSaving"
              class="px-4 py-2 bg-primary text-dark-300 hover:bg-primary-hover rounded-lg text-sm font-semibold disabled:opacity-50">
              {{ fundViewSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- Modal: 智能体量化登录授权 -->
    <transition name="modal">
      <div v-if="showOpenclawModal"
        class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
        @click.self="showOpenclawModal = false">
        <div class="bg-dark-100 rounded-xl p-6 w-full max-w-md border border-border-primary">
          <div class="flex items-center justify-between mb-4">
            <h3 class="font-bold">智能体量化登录授权 — {{ openclawUser?.username }}</h3>
            <button @click="showOpenclawModal = false" class="text-text-tertiary hover:text-text-primary">✕</button>
          </div>
          <div class="text-sm text-text-secondary mb-4">是否允许该用户登录 OpenCLAW 智能体控制台 (<a href="https://auto.hustle2026.xyz" target="_blank" class="text-primary">auto.hustle2026.xyz</a>) ？</div>
          <label class="flex items-center gap-2 mb-4 text-sm">
            <input type="checkbox" v-model="openclawEnabled" class="accent-primary">
            <span>授予 auto.hustle2026.xyz 登录权限</span>
          </label>
          <div class="text-xs text-text-tertiary mb-5">
            启用后该用户可使用自己的 admin 账号密码登录智能体控制台，并在 Settings 里添加属于其名下的作用域目标；
            禁用即撤销访问（不影响 admin 本身登录 admin.hustle2026.xyz）。
          </div>
          <div class="flex justify-end gap-2">
            <button @click="showOpenclawModal = false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">取消</button>
            <button @click="saveOpenclawToggle" :disabled="openclawSaving"
              class="px-4 py-2 bg-primary text-dark-300 hover:bg-primary-hover rounded-lg text-sm font-semibold disabled:opacity-50">
              {{ openclawSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/services/api.js'
import dayjs from 'dayjs'

// ── Tabs ──────────────────────────────────────────────────────
const tabs = [
  { id: 'users',    label: '用户账号' },
  { id: 'accounts', label: '绑定账户' },
  { id: 'mt5',      label: 'MT5客户端' },
]
const activeTab = ref('users')

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
  let detail = e?.response?.data?.detail || e?.message || ''
  // FastAPI validation error returns detail as array of objects
  if (Array.isArray(detail)) {
    detail = detail.map(d => d.msg || d.message || JSON.stringify(d)).join('; ')
  } else if (typeof detail === 'object') {
    detail = detail.msg || detail.message || JSON.stringify(detail)
  }
  toast(detail ? `${label}: ${detail}` : label, 'error')
}

// ── Formatters ────────────────────────────────────────────────
const subModalOpen = ref(false)
const subParent = ref(null)
const subList = ref([])
const subListLoading = ref(false)
const subCreating = ref(false)
const subForm = ref({ username: '', password: '', invested_cny: null, fx_override: null })

const cashEvents = ref([])
const cashflowState = ref({ virtual_shares: null, bootstrap_total_assets: null })
const cashForm = ref({ direction: 'deposit', amount_usdt: null, note: '' })
const cashSubmitting = ref(false)

async function reloadCashflow() {
  if (!subParent.value) return
  try {
    const r = await api.get(`/api/v1/users/${subParent.value.user_id}/parent-cashflow`)
    cashflowState.value = r.data.share_state || {}
    cashEvents.value = r.data.events || []
  } catch (e) {
    showToast('加载父账号资金记录失败：' + (e.response?.data?.detail || e.message), 'error')
  }
}

async function submitCashflow() {
  const f = cashForm.value
  if (!f.amount_usdt || f.amount_usdt <= 0) { showToast('金额必须 > 0', 'error'); return }
  if (!confirm(`确认${f.direction === 'deposit' ? '入金' : '出金'} ${f.amount_usdt} USDT？系统将按当下 NAV ${f.direction === 'deposit' ? '铸造' : '销毁'}对应虚拟份额。`)) return
  cashSubmitting.value = true
  try {
    const r = await api.post(`/api/v1/users/${subParent.value.user_id}/parent-cashflow`, {
      direction: f.direction,
      amount_usdt: Number(f.amount_usdt),
      note: (f.note || '').trim() || null,
    })
    showToast(`已登记：${f.direction === 'deposit' ? '入金' : '出金'} ${f.amount_usdt} USDT @ NAV ${r.data.nav_at_event.toFixed(4)}，份额 Δ ${r.data.shares_delta.toFixed(4)}`)
    cashForm.value = { direction: 'deposit', amount_usdt: null, note: '' }
    await reloadCashflow()
    await reloadSubs()   // sub 估值会因 total_assets 变化重算
  } catch (e) {
    showToast('登记失败：' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    cashSubmitting.value = false
  }
}

async function openSubAccountModal(u) {
  subParent.value = u
  subForm.value = { username: '', password: '', invested_cny: null, fx_override: null }
  subModalOpen.value = true
  await reloadSubs()
  await reloadCashflow()
}

function closeSubModal() {
  subModalOpen.value = false
  subParent.value = null
  subList.value = []
}

const m2mForm = ref({ sub_username: '', invested_cny: null, fx_override: null })
const m2mSubmitting = ref(false)

async function subscribeExistingSub() {
  if (!subParent.value) return
  const f = m2mForm.value
  if (!f.sub_username || !f.invested_cny || f.invested_cny <= 0) {
    showToast('请填写子账号用户名和投入金额', 'error'); return
  }
  // Resolve sub_username → sub_user_id
  m2mSubmitting.value = true
  try {
    const ur = await api.get('/api/v1/users/', { params: { search: f.sub_username, limit: 20 } })
    const list = ur.data?.items || ur.data || []
    const hit = list.find(u => u.username === f.sub_username && u.is_subaccount)
    if (!hit) {
      showToast(`未找到子账号用户名「${f.sub_username}」`, 'error')
      m2mSubmitting.value = false; return
    }
    const body = {
      sub_user_id: hit.user_id,
      invested_cny: Number(f.invested_cny),
      fx_override: f.fx_override ? Number(f.fx_override) : null,
    }
    const r = await api.post(`/api/v1/users/${subParent.value.user_id}/sub-accounts/subscribe-existing`, body)
    showToast(`已订阅：${f.sub_username} @ NAV ${Number(r.data.nav_per_share_at_join).toFixed(4)}，份额 ${Number(r.data.shares).toFixed(4)}`)
    m2mForm.value = { sub_username: '', invested_cny: null, fx_override: null }
    await reloadSubs()
  } catch (e) {
    showToast('订阅失败：' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    m2mSubmitting.value = false
  }
}

async function reloadSubs() {
  if (!subParent.value) return
  subListLoading.value = true
  try {
    const r = await api.get(`/api/v1/users/${subParent.value.user_id}/sub-accounts`)
    subList.value = r.data || []
  } catch (e) {
    showToast('加载子账号失败：' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    subListLoading.value = false
  }
}

async function createSub() {
  const f = subForm.value
  if (!f.username || !f.password || !f.invested_cny) {
    showToast('请填写用户名、密码、投入金额', 'error'); return
  }
  if (f.password.length < 6) { showToast('密码至少 6 位', 'error'); return }
  if (f.invested_cny <= 0) { showToast('投入金额必须 > 0', 'error'); return }
  subCreating.value = true
  try {
    const body = {
      username: f.username.trim(),
      password: f.password,
      invested_cny: Number(f.invested_cny),
    }
    if (f.fx_override && f.fx_override > 0) body.fx_override = Number(f.fx_override)
    const r = await api.post(`/api/v1/users/${subParent.value.user_id}/sub-accounts`, body)
    showToast(`子账号已创建：投入 ¥${r.data.invested_cny} = ${Number(r.data.invested_usdt).toFixed(2)} USDT，份额 ${Number(r.data.shares).toFixed(4)}`)
    subForm.value = { username: '', password: '', invested_cny: null, fx_override: null }
    await reloadSubs()
    await loadUsers()  // refresh user list to show is_subaccount badges
  } catch (e) {
    showToast('创建失败：' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    subCreating.value = false
  }
}

async function deactivateSub(row) {
  const ok = window.confirm(`停用子账号 ${row.sub_username}？停用后该用户无法登录，订阅记录保留。`)
  if (!ok) return
  try {
    await api.delete(`/api/v1/sub-accounts/${row.id}`)
    showToast('已停用')
    await reloadSubs()
    await loadUsers()
  } catch (e) {
    showToast('停用失败：' + (e.response?.data?.detail || e.message), 'error')
  }
}

async function reactivateSub(row) {
  const ok = window.confirm(`启用子账号 ${row.sub_username}？启用后该用户可重新登录。`)
  if (!ok) return
  try {
    await api.post(`/api/v1/sub-accounts/${row.id}/reactivate`)
    showToast('已启用')
    await reloadSubs()
    await loadUsers()
  } catch (e) {
    showToast('启用失败：' + (e.response?.data?.detail || e.message), 'error')
  }
}

const editingSub = ref(null)
const editSubForm = ref({ password: '', is_active: true, showPw: false, invested_cny: 0, invested_usdt: 0, shares: 0 })
const editSubSaving = ref(false)

function startEditSub(row) {
  editingSub.value = row
  editSubForm.value = {
    password: '', is_active: row.status === 'active', showPw: false,
    invested_cny: Number(row.invested_cny),
    invested_usdt: Number(row.invested_usdt),
    shares: Number(row.shares),
  }
}

async function saveEditSub() {
  if (!editingSub.value) return
  const f = editSubForm.value
  const row = editingSub.value

  if (f.password && f.password.length < 6) {
    showToast('密码至少 6 位', 'error'); return
  }

  editSubSaving.value = true
  try {
    // 1. Update user password/status if needed
    const userData = { is_active: f.is_active }
    if (f.password) userData.password = f.password
    await api.put(`/api/v1/users/${row.sub_user_id}`, userData)

    // 2. Update subscription share data if changed
    const shareData = {}
    if (f.invested_cny !== Number(row.invested_cny)) shareData.invested_cny = f.invested_cny
    if (f.invested_usdt !== Number(row.invested_usdt)) shareData.invested_usdt = f.invested_usdt
    if (f.shares !== Number(row.shares)) shareData.shares = f.shares
    if (Object.keys(shareData).length > 0) {
      await api.put(`/api/v1/sub-accounts/${row.id}`, shareData)
    }

    showToast(`子账号 ${row.sub_username} 已更新`)
    editingSub.value = null
    await reloadSubs()
    await loadUsers()
  } catch (e) {
    showToast('更新失败：' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    editSubSaving.value = false
  }
}

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
  const p = platforms.value.find(x => x.platform_id === pid)
  if (!p) return `Platform ${pid}`
  const base = p.display_name || p.platform_name
  return mt5 ? `${base} MT5` : base
}

// ── 平台辅助函数（动态，不硬编码）──────────────────
// 根据 platform_type 判断是否为 MT5 平台（Bybit、IC Markets 等）
function platformSupportsMT5(pid) {
  const p = platforms.value.find(x => x.platform_id === pid)
  return p?.platform_type === 'mt5'
}
// 默认杠杆：Binance=20x，其余=100x（可按实际平台扩展）
function defaultLeverage(pid) {
  const p = platforms.value.find(x => x.platform_id === pid)
  return (p?.platform_type === 'cex' && pid === 1) ? 20 : 100
}

// ══════════════════════════════════════════
// Tab 1 — 用户账号
// ══════════════════════════════════════════
// ── 平台数据（从 /api/v1/hedging/platforms 加载，替代硬编码）──
const platforms = ref([])
async function loadPlatforms() {
  try {
    const r = await api.get('/api/v1/hedging/platforms')
    platforms.value = r.data || []
    // 若 accountForm 还未选平台，设为第一个
    if (!accountForm.value.platform_id && platforms.value.length) {
      accountForm.value.platform_id = platforms.value[0].platform_id
    }
  } catch (e) {
    console.warn('加载平台列表失败', e)
  }
}

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
const subAccountCount = computed(() =>
  users.value.filter(u => u.is_subaccount).length
)
function isAdminUser(u) {
  return (u.rbac_roles || []).some(r => (r.role_name || r || '').includes('管理员'))
}
function hasSubAccounts(u) {
  // user has at least one active sub-account under them
  return Number(u.sub_account_count) > 0
}

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
  secretVisible.value.user_password = false
  currentUser.value = null
  userForm.value = { username: '', email: '', password: '', role: '交易员', is_active: true, feishu_open_id: '', feishu_mobile: '', feishu_union_id: '' }
  showUserModal.value = true
}

function openEditUser(u) {
  isEditUser.value = true
  secretVisible.value.user_password = false
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
      data.feishu_open_id  = userForm.value.feishu_open_id  || null
      data.feishu_mobile   = userForm.value.feishu_mobile   || null
      data.feishu_union_id = userForm.value.feishu_union_id || null
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
  } catch (e) {
    // 404 = 用户已不存在，视为删除成功
    if (e.response?.status === 404) {
      toast('用户已删除')
    } else {
      apiErr('删除失败', e)
      return
    }
  }
  await loadUsers()
}

// ── 飞书ID反查 ───────────────────────────────────────────────
const feishuLookupLoading = ref(false)

async function lookupFeishuId() {
  const mobile = userForm.value.feishu_mobile?.trim()
  if (!mobile) { toast('请先输入飞书手机号', 'error'); return }
  feishuLookupLoading.value = true
  try {
    const r = await api.post('/api/v1/users/feishu-lookup', { mobile })
    if (r.data.open_id)  userForm.value.feishu_open_id  = r.data.open_id
    if (r.data.union_id) userForm.value.feishu_union_id = r.data.union_id
    toast(r.data.name ? `已找到: ${r.data.name}` : '飞书ID已回填')
  } catch (e) { apiErr('飞书查询失败', e) }
  finally { feishuLookupLoading.value = false }
}

// ── 通知订阅分配 ─────────────────────────────────────────────
const showNotifModal   = ref(false)
const notifUser        = ref(null)
const notifLoading     = ref(false)
const notifTemplates   = ref([])   // active templates from DB
const notifTraders     = ref([])   // trader users to subscribe to
const notifSubMap      = ref({})   // { `${traderUserId}:${templateId}`: true }

const notifCategories = computed(() => {
  const cats = [...new Set(notifTemplates.value.map(t => t.category))]
  return cats.sort()
})

function templatesByCategory(cat) {
  return notifTemplates.value.filter(t => t.category === cat)
}

function notifCatLabel(cat) {
  return { risk: '风险告警', trading: '交易通知', system: '系统通知' }[cat] || cat
}

function subKey(traderID, templateID) { return `${traderID}:${templateID}` }

function isSubscribed(traderID, templateID) {
  return !!notifSubMap.value[subKey(traderID, templateID)]
}

function toggleSub(traderID, templateID) {
  const k = subKey(traderID, templateID)
  notifSubMap.value[k] = !notifSubMap.value[k]
}

function toggleAllForTrader(traderID, on) {
  for (const tpl of notifTemplates.value) {
    notifSubMap.value[subKey(traderID, tpl.template_id)] = on
  }
}

async function openNotifConfig(u) {
  notifUser.value = u
  notifSubMap.value = {}
  notifTemplates.value = []
  notifTraders.value = []
  showNotifModal.value = true
  notifLoading.value = true
  try {
    const [tplRes, subRes] = await Promise.all([
      api.get('/api/v1/notifications/templates/active'),
      api.get(`/api/v1/notifications/subscriptions/${u.user_id}`),
    ])
    notifTemplates.value = tplRes.data || []
    // Build trader list from all users (everyone can be a trader)
    notifTraders.value = users.value.filter(x => x.user_id !== u.user_id)
    // Build subscription map from existing subs
    const subs = subRes.data || []
    const map = {}
    for (const s of subs) {
      map[subKey(s.trader_user_id, s.template_id)] = true
    }
    notifSubMap.value = map
  } catch (e) { apiErr('加载通知配置失败', e) }
  finally { notifLoading.value = false }
}

async function saveNotifConfig() {
  if (!notifUser.value) return
  notifLoading.value = true
  try {
    // Group by trader_user_id
    const byTrader = {}
    for (const [key, enabled] of Object.entries(notifSubMap.value)) {
      if (!enabled) continue
      const [traderID, templateID] = key.split(':')
      if (!byTrader[traderID]) byTrader[traderID] = []
      byTrader[traderID].push(templateID)
    }
    const subscriptions = Object.entries(byTrader).map(([trader_user_id, template_ids]) => ({
      trader_user_id, template_ids
    }))
    await api.put(`/api/v1/notifications/subscriptions/${notifUser.value.user_id}`, { subscriptions })
    toast('通知订阅已保存')
    showNotifModal.value = false
  } catch (e) { apiErr('保存通知配置失败', e) }
  finally { notifLoading.value = false }
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

// ── IPIPGO 代理状态 helpers ──────────────────────────────────
const ipipgoOrders = ref([])

async function fetchIPIPGOOrders() {
  try {
    const r = await api.get('/api/v1/users/ipipgo-orders')
    ipipgoOrders.value = r.data?.orders || []
    enrichAccountsWithIPIPGO()
  } catch {}
}

function enrichAccountsWithIPIPGO() {
  for (const acc of accounts.value) {
    if (!acc.proxy_config?.region) continue
    const region = acc.proxy_config.region.replace(/[-\s]/g, '').toLowerCase()
    const order = ipipgoOrders.value.find(o => {
      const country = (o.country || '').replace(/[-\s]/g, '').toLowerCase()
      return country === region || country.includes(region) || region.includes(country)
    })
    if (order) {
      acc.proxy_config.allocated_at = acc.proxy_config.allocated_at || order.allocated_at
      acc.proxy_config.expires_at   = acc.proxy_config.expires_at   || order.expires_at
      acc.proxy_config.ip_status    = order.ip_status
      if (!acc.proxy_config.region || acc.proxy_config.region === '') {
        acc.proxy_config.region = order.country
      }
    }
  }
}

function accProxyDaysLeft(acc) {
  const exp = acc.proxy_config?.expires_at
  if (!exp) return '--'
  return Math.ceil((new Date(exp) - new Date()) / 86400000)
}

function accProxyDaysClass(acc) {
  const d = accProxyDaysLeft(acc)
  if (d === '--') return 'text-text-secondary'
  if (d <= 7) return 'text-red-400 font-bold'
  if (d <= 30) return 'text-yellow-400'
  return 'text-text-secondary'
}

function accProxyStatusClass(acc) {
  const s = acc.proxy_config?.ip_status || (acc.proxy_config?.expires_at && new Date(acc.proxy_config.expires_at) < new Date() ? 'expired' : 'active')
  return { active: 'bg-green-900/40 text-green-400', expired: 'bg-red-900/40 text-red-400', pending: 'bg-yellow-900/40 text-yellow-400', cancelled: 'bg-dark-300 text-text-tertiary' }[s] || 'bg-green-900/40 text-green-400'
}

function accProxyStatusText(acc) {
  const s = acc.proxy_config?.ip_status || (acc.proxy_config?.expires_at && new Date(acc.proxy_config.expires_at) < new Date() ? 'expired' : 'active')
  return { active: '正常', expired: '已过期', pending: '待生效', cancelled: '已取消' }[s] || '正常'
}

// ══════════════════════════════════════════
// Tab 2 — 绑定账户
// ══════════════════════════════════════════
const accounts              = ref([])
const accountsLoading       = ref(false)
const selectedAccountUserId = ref('')
const showAccountModal      = ref(false)
const secretVisible = ref({ api_secret: false, passphrase: false, mt5_password: false, proxy_password: false, user_password: false, sub_password: false })
const secretHasData = ref({ api_secret: false, passphrase: false, mt5_password: false, proxy_password: false, user_password: false, sub_password: false })
const isEditAccount         = ref(false)
const currentAccount        = ref(null)
const accountForm = ref({
  user_id: '', account_name: '', platform_id: 0,
  api_key: '', api_secret: '', passphrase: '',
  is_mt5_account: false, is_active: true, leverage: 100
})

async function loadUserAccounts() {
  accountsLoading.value = true
  accounts.value = []
  try {
    // Admin: load all accounts or filter by selected user
    const params = {}
    if (selectedAccountUserId.value) {
      params.user_id = selectedAccountUserId.value
    } else {
      params.all = 'true'
    }
    const r = await api.get('/api/v1/accounts', { params })
    const data = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    accounts.value = data.map(a => {
      const owner = users.value.find(u => u.user_id === (a.user_id || ''))
      return { ...a, _username: owner?.username || '' }
    })
    // Enrich with live IPIPGO order data
    fetchIPIPGOOrders()
  } catch (e) { apiErr('加载账户失败', e) }
  finally { accountsLoading.value = false
    // Load pair bindings for first user
    loadAllPairBindings() }
}

function onPlatformChange() {
  accountForm.value.leverage = defaultLeverage(accountForm.value.platform_id)
  if (!platformSupportsMT5(accountForm.value.platform_id)) {
    accountForm.value.is_mt5_account = false
  }
}

function openAddAccount() {
  isEditAccount.value = false
  currentAccount.value = null
  const firstPid = platforms.value[0]?.platform_id || 0
  accountForm.value = {
    user_id: selectedAccountUserId.value || '',
    account_name: '', platform_id: firstPid, api_key: '', api_secret: '',
    passphrase: '', is_mt5_account: false, is_active: true,
    leverage: defaultLeverage(firstPid)
  }
  secretVisible.value = { api_secret: false, passphrase: false }
  secretHasData.value = { api_secret: false, passphrase: false }
  showAccountModal.value = true
}

async function openEditAccount(acc) {
  isEditAccount.value = true
  currentAccount.value = acc
  accountForm.value = {
    user_id: acc.user_id || '',
    account_name: acc.account_name, platform_id: acc.platform_id,
    api_key: acc.api_key || '', api_secret: '', passphrase: '',
    is_mt5_account: acc.is_mt5_account,
    is_active: acc.is_active, leverage: acc.leverage || defaultLeverage(acc.platform_id),
    account_role: acc.account_role || ''
  }
  secretVisible.value = { api_secret: false, passphrase: false }
  secretHasData.value = { api_secret: false, passphrase: false }
  showAccountModal.value = true
  // Load actual API secret from backend (stored encrypted, shown on edit)
  try {
    const r = await api.get(`/api/v1/accounts/${acc.account_id}/secret`)
    const _sec = r.data.api_secret || ''
    const _pp = r.data.passphrase || ''
    secretHasData.value = { api_secret: !!_sec, passphrase: !!_pp }
    // Don't pre-fill — show placeholder instead so user knows it's set
    accountForm.value.api_secret = ''
    accountForm.value.passphrase = ''
  } catch { /* admin may not have bypass yet — user can re-enter manually */ }
}

// IPIPGO proxy config
const showProxyModal  = ref(false)
const proxyTargetAcc  = ref(null)
const proxyForm = ref({ proxy_type: 'socks5', host: '', port: null, username: '', password: '', region: '' })

async function fetchIpRegion(ip) {
  if (!ip) return ''
  try {
    const r = await api.get('/api/v1/users/ip-location', { params: { ip } })
    return r.data?.location || r.data?.region || ''
  } catch { return '' }
}

function openProxyConfig(acc) {
  proxyTargetAcc.value = acc
  const cfg = acc.proxy_config || {}
  // Auto-fill region from IPIPGO orders if empty
  let region = cfg.region || ''
  if (!region && ipipgoOrders.value.length) {
    const activeOrder = ipipgoOrders.value.find(o => o.ip_status === 'active')
    if (activeOrder) region = activeOrder.country || ''
  }
  proxyForm.value = {
    proxy_type: cfg.proxy_type || 'socks5',
    host:       cfg.host       || '',
    port:       cfg.port       || null,
    username:   cfg.username   || '',
    password:   cfg.password   || '',
    region:     region,
  }
  secretVisible.value.proxy_password = false
  secretHasData.value.proxy_password = !!proxyForm.value.password
  proxyForm.value.password = ''
  showProxyModal.value = true
  // Auto-fetch region from IP if not set
  if (!proxyForm.value.region && proxyForm.value.host) {
    fetchIpRegion(proxyForm.value.host).then(r => { if (r) proxyForm.value.region = r })
  }
}

async function saveProxyConfig() {
  const acc = proxyTargetAcc.value
  if (!acc) return
  const _pf = { ...proxyForm.value }
  if (!_pf.password && secretHasData.value.proxy_password) delete _pf.password
    const cfg = _pf.host ? {
    proxy_type: _pf.proxy_type,
    host:       _pf.host,
    port:       _pf.port,
    username:   _pf.username || null,
    password:   _pf.password || null,
    region:     _pf.region   || null,
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
        platform_id:    accountForm.value.platform_id,
        is_active:      accountForm.value.is_active,
        is_mt5_account: accountForm.value.is_mt5_account,
        leverage:       accountForm.value.leverage,
        account_role:   accountForm.value.account_role || null,
      }

      // Client-side role uniqueness validation
      const targetRole = data.account_role
      const targetUserId = accountForm.value.user_id || currentAccount.value?.user_id
      if (targetRole && targetUserId) {
        const sameUserAccounts = accounts.value.filter(a =>
          a.user_id === targetUserId && a.account_id !== currentAccount.value.account_id
        )
        if (targetRole === 'primary') {
          const existingPrimary = sameUserAccounts.find(a => a.account_role === 'primary')
          if (existingPrimary) {
            toast(`主账号已存在（${existingPrimary.account_name}），每个用户只能设一个主账号`, 'error')
            return
          }
        }
        if (targetRole === 'hedge') {
          // One hedge per platform per user
          const existingHedge = sameUserAccounts.find(a =>
            a.account_role === 'hedge' && a.platform_id === data.platform_id
          )
          if (existingHedge) {
            toast(`该用户在此平台已有对冲账户（${existingHedge.account_name}），每平台只能一个对冲账户`, 'error')
            return
          }
        }
      }

      if (accountForm.value.api_key)    data.api_key    = accountForm.value.api_key
      if (accountForm.value.api_secret) data.api_secret = accountForm.value.api_secret
      if (accountForm.value.passphrase) data.passphrase = accountForm.value.passphrase
      if (accountForm.value.user_id)    data.user_id    = accountForm.value.user_id
      await api.put(`/api/v1/accounts/${currentAccount.value.account_id}`, data)
      toast('账户已更新')
    } else {
      if (!accountForm.value.user_id) { toast('请选择所属用户', 'error'); return }

      // New account role validation
      const targetRole = accountForm.value.account_role
      if (targetRole) {
        const uid = accountForm.value.user_id
        const sameUserAccounts = accounts.value.filter(a => a.user_id === uid)
        if (targetRole === 'primary' && sameUserAccounts.some(a => a.account_role === 'primary')) {
          toast('该用户已有主账号，每个用户只能设一个主账号', 'error'); return
        }
        if (targetRole === 'hedge') {
          const pid = accountForm.value.platform_id
          if (sameUserAccounts.some(a => a.account_role === 'hedge' && a.platform_id === pid)) {
            toast('该用户在此平台已有对冲账户，每平台只能一个对冲账户', 'error'); return
          }
        }
      }

      await api.post('/api/v1/accounts', accountForm.value)
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
  mt5_server: '', proxy_id: null,
  priority: 1, is_active: true, is_system_service: false
})

// ── Bridge 实例管理 ──────────────────────────────────────────
const clientInstances = ref({})  // { client_id: [instances] }
const clientTerminals = ref({})  // { client_id: [terminal info from Agent] }
const showDeployModal = ref(false)
const deployClient    = ref(null)
const deployInstances = ref([])
const isEditDeploy    = ref(false)
const editingInstanceId = ref(null)
const deployProgress = ref({ active: false, done: false, error: false, title: '', percent: 0, steps: [] })

function startProgress(title, stepLabels) {
  deployProgress.value = {
    active: true, done: false, error: false, title,
    percent: 0,
    steps: stepLabels.map(label => ({ label, status: 'pending' }))
  }
}
function stepRun(idx) {
  const p = deployProgress.value
  p.steps[idx].status = 'running'
  p.percent = Math.round((idx / p.steps.length) * 100)
}
function stepDone(idx) {
  const p = deployProgress.value
  p.steps[idx].status = 'done'
  p.percent = Math.round(((idx + 1) / p.steps.length) * 100)
}
function stepError(idx, msg) {
  const p = deployProgress.value
  p.steps[idx].status = 'error'
  p.steps[idx].label += ` — ${msg}`
  p.error = true
  p.title = '操作失败'
}
function progressDone(title) {
  deployProgress.value.done = true
  deployProgress.value.percent = 100
  deployProgress.value.title = title
}

const deployForm = ref({
  instance_name: '', server_ip: '172.31.14.113', service_port: null,
  mt5_path: '', mt5_data_path: '', deploy_path: '',
  instance_type: 'primary', auto_start: true, is_portable: true
})

async function loadAllInstances() {
  try {
    const r = await api.get('/api/v1/mt5/instances')
    const all = r.data || []

    const map = {}
    for (const inst of all) {
      const cid = inst.client_id
      if (cid) {
        if (!map[cid]) map[cid] = []
        inst._live_running = inst.status === 'running'
        map[cid].push(inst)
      }
    }

    // Status from DB (maintained by Go healthwatch)

    clientInstances.value = map
  } catch {}
}

async function loadTerminals() {
  try {
    const r = await api.get('/api/v1/mt5/instances/terminal/list', {
      params: { _t: Date.now() }  // Cache buster
    })
    const all = Array.isArray(r.data) ? r.data : []
    // Deep-clone each terminal to force Vue reactivity
    const cloned = all.map(t => JSON.parse(JSON.stringify(t)))
    const map = {}
    for (const client of mt5Clients.value) {
      const cid = client.client_id
      // Priority 1: exact match via agent_instance_name (DB field)
      let matching = []
      if (client.agent_instance_name) {
        matching = cloned.filter(t => t.instance_name === client.agent_instance_name)
      }
      // Priority 2: match via display_name === client_name
      if (!matching.length) {
        matching = cloned.filter(t => t.display_name === client.client_name)
      }
      // Priority 3: fuzzy match
      if (!matching.length) {
        const cName = (client.client_name || '').toLowerCase().replace(/[^a-z0-9]/g, '-')
        matching = cloned.filter(t => {
          const tName = (t.instance_name || '').toLowerCase()
          const tDisplay = (t.display_name || '').toLowerCase().replace(/[^a-z0-9]/g, '-')
          return tName === cName || tDisplay === cName
        })
      }
      if (matching.length) map[cid] = matching
      else {
        // 新部署的但 Agent 还未识别 — 创建占位符
        if (client.agent_instance_name) {
          map[cid] = [{
            instance_name: client.agent_instance_name,
            display_name: client.client_name,
            is_running: false,
            health_status: { is_running: false, details: {} },
            _placeholder: true
          }]
        }
      }
    }
    clientTerminals.value = { ...map }  // New object reference
  } catch (e) {
    console.error('loadTerminals failed:', e)
  }
}

async function controlTerminal(instanceName, action) {
  try {
    await api.post(`/api/v1/mt5/instances/terminal/${instanceName}/control`, { action })
    toast(`MT5 终端 ${instanceName}: ${action === 'start' ? '启动' : action === 'stop' ? '停止' : '重启'}指令已发送`)
    // Multi-stage refresh to catch state transition
    await new Promise(r => setTimeout(r, 1500))
    await loadTerminals()
    setTimeout(loadTerminals, 3000)
    setTimeout(loadTerminals, 6000)
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || ''
    toast(`终端控制失败: ${detail}`, 'error')
  }
}

async function toggleSystemService(client) {
  try {
    const newVal = !client.is_system_service
    const resp = await api.put(`/api/v1/mt5-clients/${client.client_id}`, { is_system_service: newVal })
    // Immediately update local state — don't rely on loadMT5Clients succeeding
    const idx = mt5Clients.value.findIndex(c => c.client_id === client.client_id)
    if (idx >= 0) mt5Clients.value[idx].is_system_service = resp.data?.is_system_service ?? newVal
    toast(newVal ? '已设为系统服务（仅行情数据）' : '已切换为完整交易模式')
    await loadMT5Clients()
  } catch (e) { apiErr('切换失败', e) }
}

async function controlInstance(inst, action) {
  try {
    await api.post(`/api/v1/mt5/instances/${inst.instance_id}/control`, { action })
    toast(`${inst.instance_name}: ${action === 'start' ? '启动' : action === 'stop' ? '停止' : '重启'}指令已发送`)
    setTimeout(loadAllInstances, 2000)
  } catch (e) { apiErr('控制失败', e) }
}

function getInstanceStatusClass(instances) {
  if (!instances?.length) return 'bg-dark-300 text-text-tertiary'
  const active = instances.find(i => i.is_active)
  if (active?.status === 'running') return 'bg-[#0ecb81]/10 text-[#0ecb81]'
  if (active?.status === 'stopped') return 'bg-[#f0b90b]/10 text-[#f0b90b]'
  return 'bg-[#f6465d]/10 text-[#f6465d]'
}

function getClientSymbols(client) {
  // 从已部署实例的 symbols 字段获取交易品种
  const instances = clientInstances.value[client.client_id] || []
  for (const inst of instances) {
    if (inst.symbols?.length) return inst.symbols.join(', ')
  }
  return '未配置'
}

function getInstanceStatusText(instances) {
  if (!instances?.length) return '未部署'
  const active = instances.find(i => i.is_active)
  if (!active) return '无活跃实例'
  return { running: '运行中', stopped: '已停止', error: '异常' }[active.status] || active.status
}

// ── 部署品种选择 ──────────────────────────────────────
const availableDeploySymbols = ref([])

async function loadDeploySymbols(platformId) {
  try {
    // 直接从 platform_symbols 表获取该平台所有交易品种
    const r = await api.get('/api/v1/hedging/symbols', { params: { platform_id: platformId } })
    const syms = (r.data || []).map(s => s.symbol).filter(Boolean)
    availableDeploySymbols.value = syms.length ? syms : ['XAUUSD+']
  } catch {
    availableDeploySymbols.value = ['XAUUSD+']
  }
}

function toggleDeploySymbol(sym) {
  const idx = deployForm.value.symbols.indexOf(sym)
  if (idx >= 0) deployForm.value.symbols.splice(idx, 1)
  else deployForm.value.symbols.push(sym)
}

function toggleAllDeploySymbols() {
  if (deployForm.value.symbols.length === availableDeploySymbols.value.length) {
    deployForm.value.symbols = []
  } else {
    deployForm.value.symbols = [...availableDeploySymbols.value]
  }
}

async function openDeployModal(client) {
  deployClient.value = client
  isEditDeploy.value = false
  editingInstanceId.value = null
  // 加载该平台可用的 MT5 品种
  await loadDeploySymbols(client.platform_id)
  // Auto-generate paths from client_name
  const safeName = (client.client_name || 'new').toLowerCase().replace(/[^a-z0-9_-]/g, '-')
  resetDeployForm()
  deployForm.value.instance_name = `${client.client_name}-实例`
  deployForm.value.mt5_path = `D:\\MetaTrader 5-${safeName}\\terminal64.exe`
  deployForm.value.mt5_data_path = `D:\\MetaTrader 5-${safeName}`
  deployForm.value.deploy_path = `D:\\hustle-mt5-${safeName}`
  showDeployModal.value = true
  // Load instances for this client
  try {
    const r = await api.get(`/api/v1/mt5/instances/client/${client.client_id}`)
    deployInstances.value = r.data || []
  } catch { deployInstances.value = [] }
}

function resetDeployForm() {
  isEditDeploy.value = false
  editingInstanceId.value = null
  deployForm.value = {
    instance_name: deployClient.value ? `${deployClient.value.client_name}-实例` : '',
    server_ip: '172.31.14.113', service_port: null,
    mt5_path: deployClient.value?.mt5_path || '',
    mt5_data_path: deployClient.value?.mt5_data_path || '',
    deploy_path: '', instance_type: 'primary', auto_start: true, is_portable: true,
    symbols: [...availableDeploySymbols.value]  // 默认全选
  }
}

function editDeployInstance(inst) {
  isEditDeploy.value = true
  editingInstanceId.value = inst.instance_id
  deployForm.value = {
    instance_name: inst.instance_name,
    server_ip: inst.server_ip,
    service_port: inst.service_port,
    mt5_path: inst.mt5_path,
    mt5_data_path: inst.mt5_data_path || '',
    deploy_path: inst.deploy_path,
    instance_type: inst.instance_type,
    auto_start: inst.auto_start,
    is_portable: inst.is_portable ?? true,
    symbols: inst.symbols || [...availableDeploySymbols.value]
  }
}

async function saveDeploy() {
  const f = deployForm.value
  if (!f.instance_name?.trim()) { toast('请填写实例名称', 'error'); return }
  if (!f.service_port || f.service_port < 1024) { toast('请填写有效的服务端口 (1024-65535)', 'error'); return }
  if (!f.mt5_path?.trim()) { toast('请填写 MT5 安装路径', 'error'); return }
  if (!f.deploy_path?.trim()) { toast('请填写 Bridge 部署路径', 'error'); return }
  if (!f.server_ip?.trim()) { toast('请填写服务器 IP', 'error'); return }

  if (isEditDeploy.value && editingInstanceId.value) {
    try {
      await api.put(`/api/v1/mt5/instances/${editingInstanceId.value}`, f)
      toast('实例配置已更新')
      const r = await api.get(`/api/v1/mt5/instances/client/${deployClient.value.client_id}`)
      deployInstances.value = r.data || []
      resetDeployForm()
      await loadAllInstances()
    } catch (e) { apiErr('更新失败', e) }
    return
  }

  // 新建部署 — 带进度
  const steps = [
    '验证部署参数',
    '创建数据库实例记录',
    '复制 MT5 客户端模板',
    '配置 MT5 登录信息',
    '部署 Bridge 服务代码',
    '注册 NSSM Windows 服务',
    '配置崩溃自动重启策略',
    '绑定 MT5WindowsAgent 启动依赖',
    '启动 Bridge 服务',
    '创建桌面快捷方式',
    '添加防火墙入站规则',
  ]
  startProgress('正在部署 Bridge 实例...', steps)

  try {
    // Step 0: 验证
    stepRun(0); await new Promise(r => setTimeout(r, 300)); stepDone(0)

    // Step 1: 创建 DB 记录 + 调用 Agent 部署
    stepRun(1)
    await api.post(`/api/v1/mt5/instances/client/${deployClient.value.client_id}/deploy`, {
      ...f, client_id: deployClient.value.client_id,
    })
    stepDone(1)

    // Steps 2-8: Agent 内部完成，模拟进度
    for (let i = 2; i <= 10; i++) {
      stepRun(i); await new Promise(r => setTimeout(r, 400)); stepDone(i)
    }

    progressDone('Bridge 实例部署成功，正在启动服务...')
    const r = await api.get(`/api/v1/mt5/instances/client/${deployClient.value.client_id}`)
    deployInstances.value = r.data || []
    resetDeployForm()
    await loadAllInstances()

    // Auto-start Bridge service + MT5 terminal for the newly deployed instance
    const newInst = deployInstances.value.find(i => i.service_port === f.service_port)
    if (newInst) {
      try {
        // Start Bridge service
        await api.post(`/api/v1/mt5/instances/${newInst.instance_id}/control`, { action: 'start' })
        // Start MT5 terminal
        const sn = f.deploy_path.replace(/[\/]/g, '/').split('/').pop()
        await api.post(`/api/v1/mt5/instances/terminal/${sn}/control`, { action: 'start' }).catch(() => {})
      } catch {}
    }

    // Auto-close modal after 2 seconds
    setTimeout(() => {
      showDeployModal.value = false
      deployProgress.value.active = false
      loadMT5Clients()
    }, 2000)
  } catch (e) {
    const runningIdx = deployProgress.value.steps.findIndex(s => s.status === 'running')
    const detail = e?.response?.data?.detail || e?.message || ''
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail)
    stepError(runningIdx >= 0 ? runningIdx : 1, msg)
  }
}

async function deleteDeployInstance(inst) {
  if (!confirm(`确定要删除实例「${inst.instance_name}」吗？\n将停止进程、清除 Bridge 部署目录、MT5 数据目录和端口服务。`)) return

  const steps = [
    '检查实例运行状态',
    '停止 MT5 终端进程',
    '停止 Bridge NSSM 服务',
    '删除 NSSM 服务注册',
    '删除 Bridge 部署目录',
    '删除 MT5 数据目录',
    '删除桌面快捷方式',
    '删除防火墙入站规则',
    '清理数据库记录',
  ]
  startProgress(`正在删除 ${inst.instance_name}...`, steps)

  try {
    // Step 0: 检查状态
    stepRun(0)
    await new Promise(r => setTimeout(r, 300))
    stepDone(0)

    // Steps 1-6: Agent 完成删除（停止进程、删服务、删目录、删快捷方式）
    stepRun(1)
    await new Promise(r => setTimeout(r, 200))
    stepDone(1)

    stepRun(2)
    await new Promise(r => setTimeout(r, 200))
    stepDone(2)

    stepRun(3)
    // 调用后端删除（后端会调 Agent bridge_delete 传 port + login）
    stepDone(3)

    stepRun(4)
    await api.delete(`/api/v1/mt5/instances/${inst.instance_id}`)
    stepDone(4)

    stepRun(5); await new Promise(r => setTimeout(r, 300)); stepDone(5)
    stepRun(6); await new Promise(r => setTimeout(r, 200)); stepDone(6)
    stepRun(7); await new Promise(r => setTimeout(r, 200)); stepDone(7)

    // Step 8: 清理 DB
    stepRun(8)
    deployInstances.value = deployInstances.value.filter(i => i.instance_id !== inst.instance_id)
    stepDone(8)

    progressDone(`${inst.instance_name} 已完全删除`)
    await loadAllInstances()
  } catch (e) {
    const runningIdx = deployProgress.value.steps.findIndex(s => s.status === 'running')
    const detail = e?.response?.data?.detail || e?.message || ''
    stepError(runningIdx >= 0 ? runningIdx : 4, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
}

async function checkClientHealth(client) {
  const instances = clientInstances.value[client.client_id] || []
  if (!instances.length) {
    toast(`${client.client_name}: 无 Bridge 实例`, 'error'); return
  }
  try {
    let results = []
    for (const inst of instances) {
      try {
        const r = await api.get(`/api/v1/mt5/instances/${inst.instance_id}/status`)
        results.push({ name: inst.instance_name, running: r.data?.is_running, status: r.data?.status })
      } catch {
        results.push({ name: inst.instance_name, running: false, status: 'error' })
      }
    }
    const healthy = results.filter(r => r.running).length
    if (healthy > 0) {
      toast(`${client.client_name}: ${healthy}/${results.length} 运行中`)
    } else {
      toast(`${client.client_name}: 全部离线 — ${results.map(r => r.name + ': ' + r.status).join(', ')}`, 'error')
    }
    await loadAllInstances()
  } catch (e) { apiErr('健康检查失败', e) }
}

async function onMt5UserChange() {
  mt5SelectedAccountId.value = ''
  mt5Clients.value = []
  mt5Accounts.value = []
  if (!mt5SelectedUserId.value) {
    // 未选用户 → 加载所有用户的 MT5 客户端
    await loadAllMT5Clients()
    return
  }
  try {
    const r = await api.get('/api/v1/accounts', { params: { user_id: mt5SelectedUserId.value } })
    const all = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    // 显示所有 MT5 账户（Bybit MT5、IC Markets MT5 等）
    mt5Accounts.value = all.filter(a => a.is_mt5_account)
    // 自动选中第一个 MT5 账户并加载客户端
    if (mt5Accounts.value.length) {
      mt5SelectedAccountId.value = mt5Accounts.value[0].account_id
      await loadMT5Clients()
    }
  } catch (e) { apiErr('加载账户失败', e) }
}

async function loadAllMT5Clients() {
  await autoLoadMT5Tab()
}

async function autoLoadMT5Tab() {
  mt5Loading.value = true
  try {
    const r = await api.get('/api/v1/mt5-clients/dashboard')
    mt5Clients.value = r.data.clients || []
    clientInstances.value = r.data.instances_by_client || {}
  } catch (e) { apiErr('加载MT5客户端失败', e) }
  finally { mt5Loading.value = false }
  loadTerminalsLazy()
}

async function loadTerminalsLazy() {
  try {
    const r = await api.get('/api/v1/mt5/instances/terminal/list', { params: { _t: Date.now() } })
    const all = Array.isArray(r.data) ? r.data : []
    const cloned = all.map(t => JSON.parse(JSON.stringify(t)))
    const map = {}
    for (const client of mt5Clients.value) {
      const cid = client.client_id
      let matching = []
      if (client.agent_instance_name) {
        matching = cloned.filter(t => t.instance_name === client.agent_instance_name)
      }
      if (!matching.length) {
        matching = cloned.filter(t => t.display_name === client.client_name)
      }
      if (!matching.length) {
        const cName = (client.client_name || '').toLowerCase().replace(/[^a-z0-9]/g, '-')
        matching = cloned.filter(t => {
          const tName = (t.instance_name || '').toLowerCase()
          const tDisplay = (t.display_name || '').toLowerCase().replace(/[^a-z0-9]/g, '-')
          return tName === cName || tDisplay === cName
        })
      }
      if (matching.length) map[cid] = matching
      else if (client.agent_instance_name) {
        map[cid] = [{ instance_name: client.agent_instance_name, display_name: client.client_name, is_running: false, health_status: { is_running: false, details: {} }, _placeholder: true }]
      }
    }
    clientTerminals.value = { ...map }
  } catch {}
}

async function loadMT5Clients() {
  if (!mt5SelectedAccountId.value) return
  mt5Loading.value = true
  try {
    const r = await api.get(`/api/v1/accounts/${mt5SelectedAccountId.value}/mt5-clients`)
    mt5Clients.value = Array.isArray(r.data) ? r.data : (r.data?.clients ?? [])
    await loadAllInstances()
  } catch (e) { apiErr('加载MT5客户端失败', e) }
  finally { mt5Loading.value = false }
  loadTerminalsLazy()
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
    mt5_server: '', proxy_id: null,
    priority: 1, is_active: true
  }
  showMT5Modal.value = true
}

function openEditMT5(client) {
  isEditMT5.value = true
  secretVisible.value.mt5_password = false
  secretHasData.value.mt5_password = !!client.mt5_password
  currentMT5.value = client
  mt5Form.value = {
    client_name:   client.client_name,
    mt5_login:     client.mt5_login,
    mt5_password:  '',
    password_type: client.password_type || 'primary',
    mt5_server:    client.mt5_server,
    proxy_id:      client.proxy_id || null,
    priority:      client.priority,
    is_active:     client.is_active,
    is_system_service: client.is_system_service || false,
  }
  showMT5Modal.value = true
}

async function saveMT5() {
  try {
    if (isEditMT5.value) {
      const data = { ...mt5Form.value }
      if (!data.mt5_password) delete data.mt5_password
      const resp = await api.put(`/api/v1/mt5-clients/${currentMT5.value.client_id}`, data)
      // Optimistically update the local list immediately so UI refreshes even if loadMT5Clients fails
      const updated = resp.data
      const idx = mt5Clients.value.findIndex(c => c.client_id === currentMT5.value.client_id)
      if (idx >= 0 && updated) Object.assign(mt5Clients.value[idx], updated)
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
  // 检查同一用户是否已有连接的非系统服务MT5账户
  const alreadyConnected = mt5Clients.value.find(c =>
    c.client_id !== client.client_id &&
    c.connection_status === 'connected' &&
    !c.is_system_service
  )
  if (alreadyConnected && !client.is_system_service) {
    toast(`已连接MT5对冲账号「${alreadyConnected.client_name}」，无法同时连接第二个交易账户`, 'error')
    return
  }
  try {
    await api.post(`/api/v1/mt5-clients/${client.client_id}/connect`)
    toast(`${client.client_name} 已连接`)
    await loadMT5Clients()
  } catch (e) { apiErr('连接失败', e) }
}

async function disconnectMT5(client) {
  try {
    await api.post(`/api/v1/mt5-clients/${client.client_id}/disconnect`)
    toast(`${client.client_name} 已断开`)
    await loadMT5Clients()
  } catch (e) { apiErr('断开失败', e) }
}

async function deleteMT5(client) {
  // Delete protection: check connected status and running instances
  if (client.connection_status === 'connected') {
    toast('请先断开连接再删除', 'error'); return
  }
  const instances = clientInstances.value[client.client_id] || []
  const runningInst = instances.find(i => i._live_running || i.status === 'running')
  if (runningInst) {
    toast(`请先停止运行中的 Bridge 实例「${runningInst.instance_name}」再删除`, 'error'); return
  }
  if (!confirm(`确定要删除MT5客户端「${client.client_name}」吗？关联的 Bridge 实例也会被删除。`)) return
  try {
    await api.delete(`/api/v1/mt5-clients/${client.client_id}`)
    toast('MT5客户端已删除')
    await loadMT5Clients()
  } catch (e) { apiErr('删除失败', e) }
}

// ── 初始化 ────────────────────────────────────────────────────
// ── Hedge Ratio Per-User ──
const showHedgeModal = ref(false)
const hedgeUser = ref(null)
const hedgeEnabled = ref(false)
const hedgeSaving = ref(false)

// ── OpenCLAW (auto.hustle2026.xyz) login access ──
const showOpenclawModal = ref(false)
const openclawUser = ref(null)
const openclawEnabled = ref(false)
const openclawSaving = ref(false)

async function openOpenclawAccess(u) {
  openclawUser.value = u
  openclawEnabled.value = !!u.openclaw_enabled
  showOpenclawModal.value = true
}

async function saveOpenclawToggle() {
  openclawSaving.value = true
  try {
    await api.put('/api/v1/users/openclaw-access', {
      user_id: openclawUser.value?.user_id,
      enabled: openclawEnabled.value,
    })
    const idx = users.value.findIndex(u => u.user_id === openclawUser.value?.user_id)
    if (idx >= 0) users.value[idx].openclaw_enabled = openclawEnabled.value
    showOpenclawModal.value = false
    showToast(openclawEnabled.value ? '已授予智能体量化登录权限' : '已撤销智能体量化登录权限', 'success')
  } catch (e) {
    showToast('保存失败: ' + (e.response?.data?.detail || e.message), 'error')
  } finally { openclawSaving.value = false }
}

// ── Fund-view (www.hustle2026.xyz/fund-flow) access ──
const showFundViewModal = ref(false)
const fundViewUser = ref(null)
const fundViewEnabled = ref(false)
const fundViewSaving = ref(false)

async function openFundViewAccess(u) {
  fundViewUser.value = u
  fundViewEnabled.value = !!u.fund_view_enabled
  showFundViewModal.value = true
}

async function saveFundViewToggle() {
  fundViewSaving.value = true
  try {
    await api.put('/api/v1/users/fund-view-access', {
      user_id: fundViewUser.value?.user_id,
      enabled: fundViewEnabled.value,
    })
    const idx = users.value.findIndex(u => u.user_id === fundViewUser.value?.user_id)
    if (idx >= 0) users.value[idx].fund_view_enabled = fundViewEnabled.value
    showFundViewModal.value = false
    showToast(fundViewEnabled.value ? '已授予查看资金权限' : '已撤销查看资金权限', 'success')
  } catch (e) {
    showToast('保存失败: ' + (e.response?.data?.detail || e.message), 'error')
  } finally { fundViewSaving.value = false }
}

async function openHedgeRatio(u) {
  hedgeUser.value = u
  hedgeEnabled.value = !!u.hedge_ratio_enabled
  showHedgeModal.value = true
}

async function saveHedgeToggle() {
  hedgeSaving.value = true
  try {
    await api.put('/api/v1/hedge-ratio/toggle', {
      user_id: hedgeUser.value?.user_id,
      enabled: hedgeEnabled.value
    })
    const idx = users.value.findIndex(u => u.user_id === hedgeUser.value?.user_id)
    if (idx >= 0) users.value[idx].hedge_ratio_enabled = hedgeEnabled.value
    showHedgeModal.value = false
    showToast(hedgeEnabled.value ? '\u5df2\u542f\u7528\u5bf9\u51b2\u500d\u6570\u8c03\u8282' : '\u5df2\u7981\u7528\u5bf9\u51b2\u500d\u6570\u8c03\u8282', 'success')
  } catch (e) {
    showToast('\u4fdd\u5b58\u5931\u8d25: ' + (e.response?.data?.detail || e.message), 'error')
  } finally { hedgeSaving.value = false }
}

// ── Pair-Account Binding ──
const showPairBindModal = ref(false)
const pairBindAccount = ref(null)
const activePairs = ref([])
const userPairBindings = ref([])  // for modal
const allPairBindings = ref([])   // for card tags (all users)

function getAccountPairTags(acc) {
  const tags = []
  for (const b of allPairBindings.value) {
    if (b.account_a_id === acc.account_id) tags.push({ pair: b.pair_code, side: 'A' })
    if (b.account_b_id === acc.account_id) tags.push({ pair: b.pair_code, side: 'B' })
  }
  return tags
}

async function loadPairBindings(userId) {
  // Load for a specific user (used by modal)
  try {
    const r = await api.get('/api/v1/pair-accounts', { params: { user_id: userId } })
    userPairBindings.value = r.data || []
  } catch { userPairBindings.value = [] }
}

async function loadAllPairBindings() {
  // Load bindings for ALL users' accounts shown in the list
  const userIds = [...new Set(accounts.value.map(a => a._user_id || a.user_id).filter(Boolean))]
  const all = []
  for (const uid of userIds) {
    try {
      const r = await api.get('/api/v1/pair-accounts', { params: { user_id: uid } })
      if (r.data) all.push(...r.data.map(b => ({ ...b, _user_id: uid })))
    } catch {}
  }
  allPairBindings.value = all
}

async function loadActivePairs() {
  try {
    const r = await api.get('/api/v1/hedging/pairs')
    activePairs.value = (Array.isArray(r.data) ? r.data : []).filter(p => p.is_active)
  } catch { activePairs.value = [] }
}

async function openPairBindingModal(acc) {
  pairBindAccount.value = acc
  await loadActivePairs()
  await loadPairBindings(acc._user_id || acc.user_id)
  showPairBindModal.value = true
}

function isPairBound(pairCode, side) {
  const b = userPairBindings.value.find(x => x.pair_code === pairCode)
  if (!b || !pairBindAccount.value) return false
  return side === 'A' ? b.account_a_id === pairBindAccount.value.account_id : b.account_b_id === pairBindAccount.value.account_id
}

async function setPairBind(pairCode, side) {
  const accId = pairBindAccount.value?.account_id
  const userId = pairBindAccount.value?._user_id || pairBindAccount.value?.user_id
  if (!accId || !userId) return
  const existing = userPairBindings.value.find(x => x.pair_code === pairCode) || {}
  const body = {
    pair_code: pairCode,
    account_a_id: side === 'A' ? accId : (existing.account_a_id || null),
    account_b_id: side === 'B' ? accId : (existing.account_b_id || null),
  }
  try {
    await api.put('/api/v1/pair-accounts?user_id=' + userId, body)
    await loadPairBindings(userId)
    await loadAllPairBindings()
    showToast(pairCode + ' ' + (side === 'A' ? '\u4e3b\u8d26\u53f7' : '\u5bf9\u51b2\u8d26\u53f7') + ' \u5df2\u7ed1\u5b9a', 'success')
  } catch (e) { showToast('\u7ed1\u5b9a\u5931\u8d25: ' + (e.response?.data?.detail || e.message), 'error') }
}

async function clearPairBind(pairCode) {
  const userId = pairBindAccount.value?._user_id || pairBindAccount.value?.user_id
  if (!userId) return
  const existing = userPairBindings.value.find(x => x.pair_code === pairCode) || {}
  const accId = pairBindAccount.value?.account_id
  const body = {
    pair_code: pairCode,
    account_a_id: existing.account_a_id === accId ? null : existing.account_a_id,
    account_b_id: existing.account_b_id === accId ? null : existing.account_b_id,
  }
  try {
    await api.put('/api/v1/pair-accounts?user_id=' + userId, body)
    await loadPairBindings(userId)
    await loadAllPairBindings()
    showToast(pairCode + ' \u7ed1\u5b9a\u5df2\u6e05\u9664', 'success')
  } catch (e) { showToast('\u64cd\u4f5c\u5931\u8d25', 'error') }
}

onMounted(async () => {
  await loadUsers()
  await loadPlatforms()  // 加载平台数据（账户编辑下拉框使用）
  // 账户 tab 初始不加载（等用户切换到该 tab 再触发）
})
</script>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from { opacity: 0; transform: translateX(16px); }
.toast-leave-to   { opacity: 0; transform: translateX(16px); }
</style>
