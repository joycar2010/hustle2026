<template>
  <div class="container mx-auto px-4 py-6 space-y-5">

    <!-- Toast -->
    <div class="fixed top-4 right-4 z-50 space-y-2" style="max-width:380px">
      <div v-for="t in toasts" :key="t.id"
        :class="['px-4 py-3 rounded-xl shadow-lg flex items-center gap-3 text-sm font-medium transition-all',
          t.type==='success'?'bg-[#0ecb81] text-white': t.type==='error'?'bg-[#f6465d] text-white':'bg-[#f0b90b] text-dark-300']">
        <span>{{ t.message }}</span>
      </div>
    </div>

    <!-- Header -->
    <div>
      <h1 class="text-2xl font-bold">系统管理</h1>
      <p class="text-xs text-text-tertiary mt-0.5">总控平台系统配置与运维管理</p>
    </div>

    <!-- Tab Bar -->
    <div class="flex flex-wrap gap-0 border-b border-border-primary">
      <button v-for="tab in tabs" :key="tab.id" @click="activeTab = tab.id"
        :class="['px-4 py-2.5 text-sm font-medium transition-colors relative whitespace-nowrap',
          activeTab===tab.id ? 'text-text-primary' : 'text-text-tertiary hover:text-text-secondary']">
        {{ tab.label }}
        <div v-if="activeTab===tab.id" class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"></div>
      </button>
    </div>

    <!-- ===== 角色权限管理 ===== -->
    <div v-if="activeTab==='rbac'" class="space-y-4">
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold">角色权限管理</h2>
          <div class="flex gap-2">
            <button @click="openAddRole" class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">+ 新增角色</button>
            <button @click="loadRoles" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
          </div>
        </div>

        <!-- Type filter -->
        <div class="flex gap-2 mb-4">
          <button v-for="t in rbacTypeFilters" :key="t.val" @click="rbacFilter=t.val"
            :class="['px-3 py-1 rounded text-xs font-medium transition-colors',
              rbacFilter===t.val ? 'bg-primary/20 text-primary border border-primary' : 'bg-dark-200 text-text-secondary border border-border-primary hover:border-border-focus']">
            {{ t.label }}
          </button>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
              <th class="text-left py-2.5 px-3">角色名称</th>
              <th class="text-left py-2.5 px-3">角色代码</th>
              <th class="text-left py-2.5 px-3">描述</th>
              <th class="text-center py-2.5 px-3">权限数</th>
              <th class="text-center py-2.5 px-3">状态</th>
              <th class="text-right py-2.5 px-3">操作</th>
            </tr></thead>
            <tbody>
              <tr v-if="!roles.length"><td colspan="6" class="text-center py-8 text-text-tertiary">暂无角色数据</td></tr>
              <tr v-for="role in filteredRoles" :key="role.role_id||role.id"
                class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="py-2.5 px-3 font-semibold">{{ role.role_name }}</td>
                <td class="py-2.5 px-3 font-mono text-xs text-primary">{{ role.role_code }}</td>
                <td class="py-2.5 px-3 text-text-secondary text-xs">{{ role.description || '--' }}</td>
                <td class="py-2.5 px-3 text-center">
                  <span class="px-1.5 py-0.5 bg-dark-200 rounded text-xs">{{ (role.permissions||[]).length }}</span>
                </td>
                <td class="py-2.5 px-3 text-center">
                  <span :class="role.is_active!==false ? 'text-[#0ecb81]' : 'text-text-tertiary'" class="text-xs">
                    {{ role.is_active!==false ? '启用' : '禁用' }}
                  </span>
                </td>
                <td class="py-2.5 px-3 text-right">
                  <button @click="openEditRole(role)" class="text-xs text-primary hover:text-primary-hover mr-3">编辑</button>
                  <button @click="openRolePermissions(role)" class="text-xs text-[#f0b90b] hover:text-yellow-400 mr-3">权限</button>
                  <button @click="deleteRole(role)" class="text-xs text-[#f6465d] hover:text-red-400">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-3 gap-3 mt-4">
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">总角色数</div>
            <div class="text-xl font-bold">{{ roles.length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">已启用</div>
            <div class="text-xl font-bold text-[#0ecb81]">{{ roles.filter(r=>r.is_active!==false).length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">已禁用</div>
            <div class="text-xl font-bold text-text-tertiary">{{ roles.filter(r=>r.is_active===false).length }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 实时推送管理 ===== -->
    <div v-if="activeTab==='push'" class="space-y-4">
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-bold">实时推送管理</h2>
            <p class="text-xs text-text-tertiary mt-0.5">监控 Python Streamer 推送状态，动态调整频率 · 数据源: /api/v1/ws/stats</p>
          </div>
          <button @click="loadPushData" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm border border-border-primary transition-colors">刷新</button>
        </div>

        <!-- Streamer 状态面板 -->
        <div class="bg-dark-200 rounded-xl p-4 mb-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold text-sm">推流服务状态</h3>
            <div class="flex items-center gap-2">
              <span class="text-xs text-text-tertiary">连接数: {{ pushConnections }}</span>
              <span class="text-xs text-text-tertiary">{{ pushServerTime }}</span>
            </div>
          </div>
          <div class="space-y-2">
            <div v-for="(s, name) in pushStreamers" :key="name" class="bg-dark-100 rounded-lg p-3">
              <div class="flex items-center justify-between mb-1.5">
                <div class="flex items-center gap-2 text-sm">
                  <div :class="['w-2 h-2 rounded-full', s.running ? (s.error_count > 100 ? 'bg-[#f0b90b]' : 'bg-[#0ecb81] animate-pulse') : 'bg-[#f6465d]']"></div>
                  <span class="font-medium">{{ STREAMER_LABELS[name] || name }}</span>
                  <span class="text-text-tertiary text-xs">({{ name }})</span>
                </div>
                <div class="flex items-center gap-3 text-xs">
                  <span class="font-mono text-text-secondary">{{ (s.interval_ms / 1000).toFixed(1) }}s</span>
                  <span class="text-text-tertiary">推送 {{ s.broadcast_count }} 次</span>
                  <span v-if="s.error_count > 0" class="text-[#f6465d] font-mono">错误 {{ s.error_count }}</span>
                  <span :class="['px-1.5 py-0.5 rounded text-xs font-bold', s.running ? (s.error_count > 100 ? 'bg-[#f0b90b]/20 text-[#f0b90b]' : 'bg-[#0ecb81]/20 text-[#0ecb81]') : 'bg-[#f6465d]/20 text-[#f6465d]']">
                    {{ s.running ? (s.error_count > 100 ? '警告' : '运行中') : '已停止' }}
                  </span>
                </div>
              </div>
              <div class="text-xs text-text-tertiary">
                最后推送: {{ s.last_broadcast ? new Date(s.last_broadcast).toLocaleString('zh-CN') : '未推送' }}
              </div>
            </div>
            <div v-if="!Object.keys(pushStreamers).length" class="text-center text-text-tertiary text-xs py-4">加载中...</div>
          </div>
        </div>

        <!-- 推送频率调整 -->
        <div class="bg-dark-200 rounded-xl p-4 mb-4">
          <h3 class="font-semibold text-sm mb-1">推送频率调整</h3>
          <p class="text-xs text-text-tertiary mb-4">通过 POST /api/v1/ws/config 动态调整频率，立即生效</p>
          <div class="space-y-4">
            <div v-for="cfg in STREAMER_ADJUST_CONFIGS" :key="cfg.name" class="bg-dark-100 rounded-lg p-4">
              <div class="flex items-center justify-between mb-2">
                <div>
                  <div class="font-medium text-sm">{{ cfg.label }}</div>
                  <div class="text-xs text-text-tertiary">有效范围: {{ cfg.min }}s – {{ cfg.max }}s</div>
                </div>
                <div class="text-xs text-text-tertiary">当前: <span class="font-mono font-bold text-primary">{{ ((pushStreamers[cfg.name]?.interval_ms || 0) / 1000).toFixed(1) }}s</span></div>
              </div>
              <div class="flex items-center gap-3">
                <select v-model="pushNewIntervals[cfg.name]"
                  class="flex-1 px-2 py-1.5 bg-dark-300 border border-border-secondary rounded text-sm focus:outline-none focus:border-primary">
                  <option v-for="opt in cfg.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
                <button @click="applyFrequency(cfg.name)" :disabled="pushApplying[cfg.name]"
                  class="px-4 py-1.5 bg-primary hover:bg-primary-hover disabled:bg-dark-300 disabled:text-text-tertiary disabled:cursor-not-allowed rounded text-sm font-bold transition-colors whitespace-nowrap">
                  {{ pushApplying[cfg.name] ? '应用中...' : '应用' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Redis 推流通道 -->
        <div class="bg-dark-200 rounded-xl p-4">
          <h3 class="font-semibold text-sm mb-3">Redis 推流桥接通道</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div v-for="ch in REDIS_CHANNELS" :key="ch.channel" class="flex items-center justify-between p-3 bg-dark-100 rounded-lg">
              <div class="flex items-center gap-2">
                <div class="w-1.5 h-1.5 rounded-full bg-[#0ecb81]"></div>
                <span class="font-mono text-xs text-text-secondary">{{ ch.channel }}</span>
              </div>
              <span class="text-xs text-text-tertiary">{{ ch.desc }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 通知服务 ===== -->
    <div v-if="activeTab==='notify'" class="space-y-4">

      <!-- 飞书机器人配置 -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-bold">飞书机器人配置</h2>
            <p class="text-xs text-text-tertiary mt-0.5">配置飞书应用凭证，用于发送交易通知和告警</p>
          </div>
          <div class="flex items-center gap-2">
            <div :class="['w-2 h-2 rounded-full', feishuStatus.connected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
            <span :class="['text-xs font-medium', feishuStatus.connected ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
              {{ feishuStatus.connected ? '已连接' : '未连接' }}
            </span>
            <span v-if="feishuStatus.token_expires_at" class="text-xs text-text-tertiary ml-1">
              Token 到期: {{ feishuStatus.token_expires_at }}
            </span>
          </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-xs text-text-secondary mb-1">App ID</label>
            <input v-model="feishuConfig.app_id" type="text" placeholder="cli_xxxxxxxxxxxxxxxxxx"
              autocomplete="off"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">App Secret</label>
            <div class="relative">
              <input v-model="feishuConfig.app_secret" :type="showAppSecret ? 'text' : 'password'" placeholder="••••••••••••••••"
                autocomplete="new-password"
                class="w-full px-3 py-2 pr-9 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
              <button @click="showAppSecret=!showAppSecret" class="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-secondary text-xs">
                {{ showAppSecret ? '隐藏' : '显示' }}
              </button>
            </div>
          </div>
        </div>
        <div class="mt-4">
          <label class="block text-xs text-text-secondary mb-1">测试接收人</label>
          <div class="flex gap-2">
            <select v-model="testRecipient" class="flex-1 px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="">-- 手动输入 --</option>
              <option v-for="u in notifyUsers" :key="u.user_id" :value="u.feishu_open_id || u.feishu_mobile">
                {{ u.username }}{{ u.feishu_open_id ? ' (Open ID)' : u.feishu_mobile ? ' (手机号)' : ' (无飞书)' }}
              </option>
            </select>
            <input v-if="!testRecipient" v-model="testRecipientManual" type="text" placeholder="open_id 或手机号"
              class="flex-1 px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
        </div>
        <div class="flex gap-2 mt-4">
          <button @click="saveFeishuConfig" class="px-4 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存配置</button>
          <button @click="checkFeishuStatus" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">检测连接</button>
          <button @click="sendTestNotification" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">发送测试</button>
        </div>
      </div>

      <!-- 停市配置 -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-bold">停市时间配置</h2>
            <p class="text-xs text-text-tertiary mt-0.5">配置黄金市场开市/收市时间，影响通知触发策略</p>
          </div>
          <div class="flex items-center gap-2">
            <div :class="['w-2 h-2 rounded-full', marketStatus.is_open ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
            <span :class="['text-xs font-medium', marketStatus.is_open ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
              {{ marketStatus.is_open ? '当前开市' : '当前停市' }}
            </span>
          </div>
        </div>
        <div class="flex items-center gap-3 mb-4">
          <span class="text-sm">启用停市检测</span>
          <div @click="marketClosureConfig.enabled = !marketClosureConfig.enabled"
            :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors', marketClosureConfig.enabled ? 'bg-primary' : 'bg-gray-600']">
            <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', marketClosureConfig.enabled ? 'translate-x-4' : 'translate-x-0.5']"/>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-6">
          <div>
            <h4 class="text-xs font-semibold text-text-secondary mb-2">夏令时 (Summer)</h4>
            <div class="space-y-2">
              <div class="flex items-center gap-2">
                <span class="text-xs text-text-tertiary w-12">开市</span>
                <input v-model="marketClosureConfig.summer_open" type="text" placeholder="周一 06:00"
                  class="flex-1 px-2 py-1 bg-dark-200 border border-border-primary rounded text-sm focus:outline-none focus:border-primary" />
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs text-text-tertiary w-12">收市</span>
                <input v-model="marketClosureConfig.summer_close" type="text" placeholder="周六 05:00"
                  class="flex-1 px-2 py-1 bg-dark-200 border border-border-primary rounded text-sm focus:outline-none focus:border-primary" />
              </div>
            </div>
          </div>
          <div>
            <h4 class="text-xs font-semibold text-text-secondary mb-2">冬令时 (Winter)</h4>
            <div class="space-y-2">
              <div class="flex items-center gap-2">
                <span class="text-xs text-text-tertiary w-12">开市</span>
                <input v-model="marketClosureConfig.winter_open" type="text" placeholder="周一 07:00"
                  class="flex-1 px-2 py-1 bg-dark-200 border border-border-primary rounded text-sm focus:outline-none focus:border-primary" />
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs text-text-tertiary w-12">收市</span>
                <input v-model="marketClosureConfig.winter_close" type="text" placeholder="周六 06:00"
                  class="flex-1 px-2 py-1 bg-dark-200 border border-border-primary rounded text-sm focus:outline-none focus:border-primary" />
              </div>
            </div>
          </div>
        </div>
        <div class="flex gap-2 mt-4">
          <button @click="saveMarketClosureConfig" class="px-4 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存停市配置</button>
          <button @click="loadMarketStatus" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新市场状态</button>
        </div>
      </div>

      <!-- 通知模板管理 -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold">通知模板管理</h2>
          <button @click="loadTemplates" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
        </div>
        <!-- 分类过滤 -->
        <div class="flex gap-2 mb-4 flex-wrap">
          <button v-for="cat in templateCategories" :key="cat.val" @click="templateCategoryFilter=cat.val"
            :class="['px-3 py-1 rounded text-xs font-medium transition-colors',
              templateCategoryFilter===cat.val ? 'bg-primary/20 text-primary border border-primary' : 'bg-dark-200 text-text-secondary border border-border-primary hover:border-border-focus']">
            {{ cat.label }}
          </button>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
              <th class="text-left py-2 px-3">模板名称</th>
              <th class="text-left py-2 px-3">分类</th>
              <th class="text-left py-2 px-3">渠道</th>
              <th class="text-center py-2 px-3">优先级</th>
              <th class="text-left py-2 px-3">告警音</th>
              <th class="text-center py-2 px-3">状态</th>
              <th class="text-right py-2 px-3">操作</th>
            </tr></thead>
            <tbody>
              <tr v-if="!filteredTemplates.length"><td colspan="7" class="text-center py-8 text-text-tertiary">暂无模板数据</td></tr>
              <tr v-for="tpl in filteredTemplates" :key="tpl.template_id"
                class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="py-2 px-3 font-medium text-xs">{{ tpl.template_name }}</td>
                <td class="py-2 px-3">
                  <span :class="getCategoryClass(tpl.category)" class="px-1.5 py-0.5 rounded text-xs font-medium">
                    {{ getCategoryLabel(tpl.category) }}
                  </span>
                </td>
                <td class="py-2 px-3">
                  <div class="flex gap-1 flex-wrap">
                    <span v-if="tpl.enable_feishu" class="px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">飞书</span>
                    <span v-if="tpl.enable_email" class="px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded text-xs">邮件</span>
                    <span v-if="tpl.enable_sms" class="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs">短信</span>
                  </div>
                </td>
                <td class="py-2 px-3 text-center">
                  <span :class="getPriorityClass(tpl.priority)" class="px-1.5 py-0.5 rounded text-xs font-bold">{{ getPriorityLabel(tpl.priority) }}</span>
                </td>
                <td class="py-2 px-3 text-xs text-text-secondary">
                  {{ tpl.alert_sound_file || '无' }}
                  <span v-if="tpl.alert_sound_repeat > 1" class="text-text-tertiary">×{{ tpl.alert_sound_repeat }}</span>
                </td>
                <td class="py-2 px-3 text-center">
                  <div @click="toggleTemplate(tpl)"
                    :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors', tpl.is_enabled ? 'bg-primary' : 'bg-gray-600']">
                    <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', tpl.is_enabled ? 'translate-x-4' : 'translate-x-0.5']"/>
                  </div>
                </td>
                <td class="py-2 px-3 text-right">
                  <button @click="openEditTemplate(tpl)" class="text-xs text-primary hover:text-primary-hover mr-2">编辑</button>
                  <button @click="sendTestTemplate(tpl)" class="text-xs text-[#f0b90b] hover:text-yellow-400">测试</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 发送日志 -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold">发送日志</h2>
          <button @click="loadNotifyLogs" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
        </div>
        <div class="flex gap-3 mb-4">
          <select v-model="notifyLogFilters.service_type" @change="loadNotifyLogs" class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
            <option value="">全部服务</option>
            <option value="feishu">飞书</option>
            <option value="email">邮件</option>
          </select>
          <select v-model="notifyLogFilters.status" @change="loadNotifyLogs" class="px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="pending">待发</option>
          </select>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
              <th class="text-left py-2 px-3">模板</th>
              <th class="text-left py-2 px-3">服务</th>
              <th class="text-left py-2 px-3">接收人</th>
              <th class="text-left py-2 px-3">标题</th>
              <th class="text-center py-2 px-3">状态</th>
              <th class="text-left py-2 px-3">时间</th>
            </tr></thead>
            <tbody>
              <tr v-if="!notifyLogs.length"><td colspan="6" class="text-center py-8 text-text-tertiary">暂无日志</td></tr>
              <tr v-for="log in notifyLogs" :key="log.log_id||log.id"
                class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="py-2 px-3 text-xs">{{ log.template_name || '--' }}</td>
                <td class="py-2 px-3 text-xs text-text-secondary">{{ log.service_type }}</td>
                <td class="py-2 px-3 text-xs text-text-secondary">{{ log.recipient || '--' }}</td>
                <td class="py-2 px-3 text-xs max-w-[180px] truncate">{{ log.title }}</td>
                <td class="py-2 px-3 text-center">
                  <span :class="log.status==='success' ? 'text-[#0ecb81]' : log.status==='failed' ? 'text-[#f6465d]' : 'text-[#f0b90b]'" class="text-xs font-medium">
                    {{ log.status==='success' ? '成功' : log.status==='failed' ? '失败' : '待发' }}
                  </span>
                </td>
                <td class="py-2 px-3 text-xs text-text-tertiary">{{ log.created_at ? log.created_at.slice(0,16).replace('T',' ') : '--' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 提醒声音管理 -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-bold">提醒声音管理</h2>
            <p class="text-xs text-text-tertiary mt-0.5">管理用于通知模板的告警音文件，支持同步至飞书云端</p>
          </div>
          <div class="flex gap-2">
            <button @click="loadSounds" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
            <button @click="importExistingSounds" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">导入已有</button>
            <button @click="syncSoundsToFeishu" class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white">同步飞书</button>
          </div>
        </div>
        <!-- 上传 -->
        <div class="bg-dark-200 rounded-xl p-4 mb-4">
          <h3 class="text-xs font-semibold text-text-secondary mb-2">上传新文件</h3>
          <div class="flex gap-3 items-center">
            <input ref="soundFileInput" type="file" accept=".mp3,.wav,.ogg,.opus" @change="onSoundFileSelected"
              class="flex-1 text-sm text-text-secondary file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-dark-300 file:text-text-primary hover:file:bg-dark-50 cursor-pointer" />
            <button @click="uploadSoundFile" :disabled="!selectedSoundFile || soundUploading"
              class="px-4 py-1.5 bg-primary hover:bg-primary-hover disabled:bg-dark-300 disabled:text-text-tertiary disabled:cursor-not-allowed text-dark-300 font-semibold rounded-lg text-sm whitespace-nowrap">
              {{ soundUploading ? '上传中...' : '上传' }}
            </button>
          </div>
        </div>
        <!-- 文件列表 -->
        <div class="space-y-2">
          <div v-if="!sounds.length" class="text-center py-6 text-text-tertiary text-sm">暂无声音文件</div>
          <div v-for="s in sounds" :key="s.filename"
            class="flex items-center justify-between p-3 bg-dark-200 rounded-xl">
            <div class="flex items-center gap-3 min-w-0">
              <div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                <span class="text-primary text-xs">♪</span>
              </div>
              <div class="min-w-0">
                <div class="text-sm font-medium truncate">{{ s.filename }}</div>
                <div class="flex items-center gap-2 mt-0.5">
                  <span class="text-xs text-text-tertiary">{{ formatFileSize(s.size) }}</span>
                  <span v-if="s.is_synced" class="px-1.5 py-0.5 bg-[#0ecb81]/20 text-[#0ecb81] rounded text-xs" :title="s.file_key">已同步</span>
                  <span v-else class="px-1.5 py-0.5 bg-gray-500/20 text-gray-400 rounded text-xs">未同步</span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <button @click="playSound(s.filename)" class="px-2.5 py-1 bg-dark-300 hover:bg-dark-50 rounded text-xs">▶ 播放</button>
              <button @click="deleteSound(s.filename)" class="px-2.5 py-1 bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] rounded text-xs">删除</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 编辑模板弹窗 -->
      <div v-if="editDialogVisible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
        <div class="bg-dark-100 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
          <div class="flex items-center justify-between p-5 border-b border-border-primary">
            <h3 class="text-base font-bold">编辑通知模板</h3>
            <button @click="editDialogVisible=false" class="text-text-tertiary hover:text-text-primary text-lg leading-none">×</button>
          </div>
          <div class="p-5 space-y-4" v-if="editingTemplate">
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-xs text-text-secondary mb-1">模板名称</label>
                <input v-model="editingTemplate.template_name" type="text"
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
              </div>
              <div>
                <label class="block text-xs text-text-secondary mb-1">优先级</label>
                <select v-model.number="editingTemplate.priority"
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
                  <option :value="1">低</option>
                  <option :value="2">中</option>
                  <option :value="3">高</option>
                  <option :value="4">紧急</option>
                </select>
              </div>
            </div>
            <div>
              <label class="block text-xs text-text-secondary mb-1">标题模板</label>
              <input v-model="editingTemplate.title_template" type="text"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
            </div>
            <div>
              <label class="block text-xs text-text-secondary mb-1">内容模板</label>
              <textarea v-model="editingTemplate.content_template" rows="4"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary resize-none"></textarea>
            </div>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-xs text-text-secondary mb-1">冷却时间 (秒)</label>
                <input v-model.number="editingTemplate.cooldown_seconds" type="number" min="0"
                  class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
              </div>
              <div class="flex items-center gap-3 mt-5">
                <span class="text-sm text-text-secondary">自动检测</span>
                <div @click="editingTemplate.auto_check_enabled=!editingTemplate.auto_check_enabled"
                  :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors', editingTemplate.auto_check_enabled ? 'bg-primary' : 'bg-gray-600']">
                  <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', editingTemplate.auto_check_enabled ? 'translate-x-4' : 'translate-x-0.5']"/>
                </div>
              </div>
            </div>
            <div>
              <label class="block text-xs text-text-secondary mb-2">推送渠道</label>
              <div class="flex gap-4">
                <label class="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" v-model="editingTemplate.enable_feishu" class="accent-primary" />
                  <span class="text-sm">飞书</span>
                </label>
                <label class="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" v-model="editingTemplate.enable_email" class="accent-primary" />
                  <span class="text-sm">邮件</span>
                </label>
                <label class="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" v-model="editingTemplate.enable_sms" class="accent-primary" />
                  <span class="text-sm">短信</span>
                </label>
              </div>
            </div>
            <div class="bg-dark-200 rounded-xl p-4">
              <h4 class="text-xs font-semibold text-text-secondary mb-3">告警声音设置</h4>
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-xs text-text-tertiary mb-1">音频文件</label>
                  <select v-model="editingTemplate.alert_sound_file"
                    class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
                    <option value="">无</option>
                    <option v-for="sf in availableSounds" :key="sf.filename" :value="sf.filename">{{ sf.filename }}</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-text-tertiary mb-1">重复次数</label>
                  <input v-model.number="editingTemplate.alert_sound_repeat" type="number" min="1" max="10"
                    class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
                </div>
              </div>
              <button v-if="editingTemplate.alert_sound_file" @click="playSound(editingTemplate.alert_sound_file)"
                class="mt-2 px-3 py-1 bg-dark-300 hover:bg-dark-50 rounded text-xs">▶ 试听</button>
            </div>
          </div>
          <div class="flex justify-end gap-2 p-5 border-t border-border-primary">
            <button @click="editDialogVisible=false" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">取消</button>
            <button @click="saveTemplate" class="px-4 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存</button>
          </div>
        </div>
      </div>

    </div>

    <!-- ===== 安全组件管理 ===== -->
    <div v-if="activeTab==='security'" class="space-y-4">
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold">安全组件管理</h2>
          <button @click="loadSecurityComponents" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
        </div>

        <!-- Type filters -->
        <div class="flex gap-2 mb-4">
          <button v-for="t in securityTypeFilters" :key="t.val" @click="securityFilter=t.val"
            :class="['px-3 py-1 rounded text-xs font-medium transition-colors',
              securityFilter===t.val ? 'bg-primary/20 text-primary border border-primary' : 'bg-dark-200 text-text-secondary border border-border-primary hover:border-border-focus']">
            {{ t.label }}
          </button>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
              <th class="text-left py-2.5 px-3">组件名称</th>
              <th class="text-left py-2.5 px-3">组件代码</th>
              <th class="text-left py-2.5 px-3">类型</th>
              <th class="text-center py-2.5 px-3">状态</th>
              <th class="text-center py-2.5 px-3">优先级</th>
              <th class="text-left py-2.5 px-3">最后检查</th>
              <th class="text-right py-2.5 px-3">操作</th>
            </tr></thead>
            <tbody>
              <tr v-if="!filteredSecurityComponents.length">
                <td colspan="7" class="text-center py-8 text-text-tertiary">暂无安全组件数据</td>
              </tr>
              <tr v-for="comp in filteredSecurityComponents" :key="comp.component_id||comp.name"
                class="border-b border-border-secondary hover:bg-dark-50">
                <td class="py-2.5 px-3">
                  <div class="font-medium">{{ comp.component_name || comp.name }}</div>
                  <div class="text-xs text-text-tertiary">{{ comp.description }}</div>
                </td>
                <td class="py-2.5 px-3 font-mono text-xs">{{ comp.component_code || '--' }}</td>
                <td class="py-2.5 px-3">
                  <span :class="getCompTypeClass(comp.component_type||comp.type)" class="px-1.5 py-0.5 rounded text-xs">
                    {{ getCompTypeLabel(comp.component_type||comp.type) }}
                  </span>
                </td>
                <td class="py-2.5 px-3 text-center">
                  <span :class="(comp.is_enabled||comp.enabled) ? 'text-[#0ecb81]' : 'text-text-tertiary'" class="text-xs">
                    {{ (comp.is_enabled||comp.enabled) ? '已启用' : '已禁用' }}
                  </span>
                  <span v-if="comp.status==='error'" class="text-[#f6465d] text-xs ml-1">(错误)</span>
                </td>
                <td class="py-2.5 px-3 text-center text-xs font-mono">{{ comp.priority ?? '--' }}</td>
                <td class="py-2.5 px-3 text-xs text-text-tertiary">
                  {{ comp.last_check_at ? fmtDate(comp.last_check_at) : '--' }}
                </td>
                <td class="py-2.5 px-3 text-right whitespace-nowrap">
                  <button v-if="!(comp.is_enabled||comp.enabled)" @click="enableComponent(comp)"
                    class="text-xs text-[#0ecb81] hover:text-green-400 mr-2">启用</button>
                  <button v-else @click="disableComponent(comp)"
                    class="text-xs text-[#f0b90b] hover:text-yellow-400 mr-2">禁用</button>
                  <button @click="openCompConfig(comp)" class="text-xs text-primary hover:text-primary-hover mr-2">配置</button>
                  <button @click="viewCompLogs(comp)" class="text-xs text-text-secondary hover:text-text-primary">日志</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-4 gap-3 mt-4">
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">总组件数</div>
            <div class="text-xl font-bold">{{ securityComponents.length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">已启用</div>
            <div class="text-xl font-bold text-[#0ecb81]">{{ securityComponents.filter(c=>c.is_enabled||c.enabled).length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">已禁用</div>
            <div class="text-xl font-bold text-text-tertiary">{{ securityComponents.filter(c=>!(c.is_enabled||c.enabled)).length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">错误状态</div>
            <div class="text-xl font-bold text-[#f6465d]">{{ securityComponents.filter(c=>c.status==='error').length }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== SSL 证书管理 ===== -->
    <div v-if="activeTab==='ssl'" class="space-y-4">
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold">SSL 证书管理</h2>
          <button @click="loadCurrentCert" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
        </div>

        <!-- All certificates from live check -->
        <div v-if="allCerts.length" class="space-y-3">
          <div v-for="cert in allCerts" :key="cert.cert_path || cert.domain_names?.[0]"
            class="bg-dark-200 rounded-xl p-4 border" :class="cert.status === 'healthy' ? 'border-green-800/30' : cert.status === 'warning' ? 'border-yellow-800/30' : 'border-red-800/30'">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <div :class="['w-2 h-2 rounded-full', cert.status === 'healthy' ? 'bg-[#0ecb81] animate-pulse' : cert.status === 'warning' ? 'bg-[#f0b90b]' : 'bg-[#f6465d]']"></div>
                <span class="font-semibold text-sm">{{ cert.domain_names?.[0] || '--' }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span :class="getCertStatusClass(cert.status)" class="px-2 py-0.5 rounded text-xs font-bold">{{ getCertStatusText(cert.status) }}</span>
                <span v-if="cert.is_valid" class="text-[#0ecb81] text-xs font-mono">{{ cert.days_remaining }}天</span>
              </div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div>
                <div class="text-text-tertiary mb-0.5">剩余天数</div>
                <div class="font-mono font-bold" :class="getDaysClass(cert.days_remaining)">{{ cert.days_remaining }} 天</div>
              </div>
              <div>
                <div class="text-text-tertiary mb-0.5">颁发者</div>
                <div class="text-text-secondary truncate">{{ cert.issuer || "Let's Encrypt" }}</div>
              </div>
              <div>
                <div class="text-text-tertiary mb-0.5">颁发时间</div>
                <div class="text-text-secondary">{{ fmtDate(cert.issued_at) }}</div>
              </div>
              <div>
                <div class="text-text-tertiary mb-0.5">过期时间</div>
                <div :class="cert.days_remaining<=30 ? 'text-[#f0b90b]' : 'text-text-secondary'">{{ fmtDate(cert.expires_at) }}</div>
              </div>
            </div>
            <div class="mt-2 text-xs font-mono text-text-tertiary">
              证书: {{ cert.cert_path }} · 私钥: {{ cert.key_path }}
            </div>
            <div v-if="cert.days_remaining<=30" class="mt-2 px-3 py-2 bg-[#f0b90b]/10 border border-[#f0b90b]/30 rounded-lg text-xs text-[#f0b90b]">
              ⚠ 证书将在 {{ cert.days_remaining }} 天后过期，请及时续期
            </div>
          </div>
        </div>
        <div v-else-if="currentCert && !currentCert.exists" class="bg-dark-200 rounded-xl p-6 text-center text-text-tertiary text-sm">
          {{ currentCert.error || '未检测到SSL证书' }}
        </div>

        <!-- DB list of SSL certs -->
        <div class="mt-4 space-y-2">
          <h3 class="font-semibold text-sm mb-2">已注册证书</h3>
          <div v-for="cert in sslCerts" :key="cert.id" class="bg-dark-200 rounded-xl p-4 flex items-center justify-between">
            <div>
              <div class="font-semibold font-mono text-sm">{{ cert.domain_name || cert.domain || '--' }}</div>
              <div class="text-xs text-text-tertiary mt-0.5">
                颁发: {{ cert.issuer || 'Let\'s Encrypt' }} · 到期: {{ cert.expires_at || cert.expiry_date || '--' }}
              </div>
              <div class="text-xs text-text-tertiary">路径: {{ cert.cert_path || '--' }}</div>
            </div>
            <span :class="certStatusClass(cert)" class="px-2 py-0.5 rounded text-xs font-medium">{{ certStatusText(cert) }}</span>
          </div>
          <div v-if="!sslCerts.length" class="text-center py-6 text-text-tertiary text-sm">暂无已注册证书</div>
        </div>
      </div>
    </div>

    <!-- ===== 系统日志 ===== -->
    <div v-if="activeTab==='logs'" class="space-y-4">
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold">系统日志管理</h2>
          <div class="flex gap-2">
            <button @click="clearOldLogs" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">清理旧日志</button>
            <button @click="loadSystemLogs" class="px-3 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新</button>
          </div>
        </div>

        <!-- Filters -->
        <div class="grid grid-cols-3 gap-3 mb-4">
          <div>
            <label class="block text-xs text-text-secondary mb-1">日志级别</label>
            <select v-model="logFilters.level" @change="loadSystemLogs"
              class="w-full px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="">全部</option>
              <option value="info">INFO</option>
              <option value="warning">WARNING</option>
              <option value="error">ERROR</option>
              <option value="critical">CRITICAL</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">日志类别</label>
            <select v-model="logFilters.category" @change="loadSystemLogs"
              class="w-full px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option value="">全部</option>
              <option value="api">API</option>
              <option value="trade">交易</option>
              <option value="system">系统</option>
              <option value="auth">认证</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">显示数量</label>
            <select v-model="logFilters.limit" @change="loadSystemLogs"
              class="w-full px-3 py-1.5 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary">
              <option :value="50">50条</option>
              <option :value="100">100条</option>
              <option :value="200">200条</option>
              <option :value="500">500条</option>
            </select>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
              <th class="text-left py-2.5 px-3">时间</th>
              <th class="text-left py-2.5 px-3">级别</th>
              <th class="text-left py-2.5 px-3">类别</th>
              <th class="text-left py-2.5 px-3">消息</th>
              <th class="text-left py-2.5 px-3">用户</th>
              <th class="text-right py-2.5 px-3">操作</th>
            </tr></thead>
            <tbody>
              <tr v-if="!systemLogs.length">
                <td colspan="6" class="text-center py-8 text-text-tertiary">暂无日志数据</td>
              </tr>
              <tr v-for="log in systemLogs" :key="log.log_id||log.id"
                class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="py-2 px-3 text-xs text-text-tertiary whitespace-nowrap">{{ fmtDate(log.timestamp||log.time) }}</td>
                <td class="py-2 px-3">
                  <span :class="getLogLevelClass(log.level)" class="px-1.5 py-0.5 rounded text-xs font-bold">
                    {{ (log.level||'').toUpperCase() }}
                  </span>
                </td>
                <td class="py-2 px-3">
                  <span :class="getLogCatClass(log.category)" class="px-1.5 py-0.5 rounded text-xs">
                    {{ getLogCatLabel(log.category) }}
                  </span>
                </td>
                <td class="py-2 px-3 text-xs max-w-xs truncate">{{ log.message }}</td>
                <td class="py-2 px-3 text-xs text-text-tertiary">{{ log.user_id ? String(log.user_id).substring(0,8) : '--' }}</td>
                <td class="py-2 px-3 text-right">
                  <button @click="openLogDetail(log)" class="text-xs text-primary hover:text-primary-hover">详情</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-5 gap-2 mt-4">
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">总日志数</div>
            <div class="text-lg font-bold">{{ systemLogs.length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">INFO</div>
            <div class="text-lg font-bold text-primary">{{ systemLogs.filter(l=>l.level==='info').length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">WARNING</div>
            <div class="text-lg font-bold text-[#f0b90b]">{{ systemLogs.filter(l=>l.level==='warning').length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">ERROR</div>
            <div class="text-lg font-bold text-[#f6465d]">{{ systemLogs.filter(l=>l.level==='error').length }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-3 text-center">
            <div class="text-xs text-text-tertiary mb-1">CRITICAL</div>
            <div class="text-lg font-bold text-[#f6465d]">{{ systemLogs.filter(l=>l.level==='critical').length }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 版本管理 ===== -->
    <div v-if="activeTab==='version'" class="space-y-4">
      <div class="card">
        <h2 class="text-lg font-bold mb-4">系统版本管理</h2>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">前端版本 (Admin)</div>
            <div class="text-2xl font-mono font-bold text-primary">v2.0.0</div>
            <div class="text-xs text-text-tertiary mt-1">构建: {{ sysInfo.frontend_build_time ? fmtDate(sysInfo.frontend_build_time) : '--' }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">后端版本</div>
            <div class="text-2xl font-mono font-bold text-primary">v2.0.0</div>
            <div class="text-xs text-text-tertiary mt-1">Go + Python: {{ sysInfo.python_version || '--' }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">数据库</div>
            <div class="text-lg font-mono font-bold">PostgreSQL {{ sysInfo.db_version || '' }}</div>
            <div class="text-xs text-[#0ecb81] mt-1">● GO服务器 127.0.0.1:5432 正常</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">运行时长</div>
            <div class="text-lg font-mono font-bold">{{ sysInfo.uptime || '--' }}</div>
            <div class="text-xs text-text-tertiary mt-1">启动: {{ sysInfo.start_time || '--' }}</div>
          </div>
        </div>

        <!-- GitHub版本管理 -->
        <div class="bg-dark-200 rounded-xl p-5">
          <h3 class="font-bold mb-1">GitHub 版本备份 (分支: GO)</h3>
          <div class="text-xs text-text-tertiary mb-3">
            推送目标: <span class="font-mono text-primary">https://github.com/joycar2010/hustle2026.git @ GO</span>
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2 text-text-secondary">推送备注</label>
            <input v-model="pushRemark" type="text" placeholder="v2.0.0 - 功能更新说明（可选）"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded-lg focus:outline-none focus:border-primary text-sm" />
          </div>
          <div class="flex gap-3 mb-5">
            <button @click="pushToGitHub" :disabled="pushing"
              class="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
              {{ pushing ? '推送中...' : '推送到 GO 分支' }}
            </button>
            <button @click="refreshVersionHistory"
              class="flex items-center gap-2 px-4 py-2 bg-dark-300 hover:bg-dark-50 rounded-lg text-sm transition-colors">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              刷新 GO 分支记录
            </button>
          </div>

          <h4 class="font-semibold text-sm mb-3">GO 分支备份记录</h4>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
                <th class="text-left py-2 px-3">版本</th>
                <th class="text-left py-2 px-3">提交信息</th>
                <th class="text-left py-2 px-3">时间</th>
                <th class="text-left py-2 px-3">提交者</th>
                <th class="text-right py-2 px-3">操作</th>
              </tr></thead>
              <tbody>
                <tr v-for="v in versionHistory" :key="v.hash" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-2.5 px-3 font-mono text-xs text-primary">{{ v.hash?.substring(0,7) }}</td>
                  <td class="py-2.5 px-3 text-text-secondary text-xs">{{ v.message }}</td>
                  <td class="py-2.5 px-3 text-text-tertiary text-xs">{{ v.date }}</td>
                  <td class="py-2.5 px-3 text-text-tertiary text-xs">{{ v.author }}</td>
                  <td class="py-2.5 px-3 text-right whitespace-nowrap">
                    <button @click="rollback(v.hash)" class="text-xs text-[#f0b90b] hover:text-yellow-400 mr-2">回滚</button>
                    <button @click="deleteVersion(v.hash)" class="text-xs text-[#f6465d] hover:text-red-400">删除</button>
                  </td>
                </tr>
                <tr v-if="!versionHistory.length">
                  <td colspan="5" class="text-center py-6 text-text-tertiary text-sm">暂无备份记录</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 数据库管理 ===== -->
    <div v-if="activeTab==='database'" class="space-y-4">
      <div class="card">
        <h2 class="text-lg font-bold mb-4">PostgreSQL 数据库管理 (GO服务器)</h2>

        <!-- 统计卡片 -->
        <div class="grid grid-cols-3 gap-3 mb-5">
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">数据库大小</div>
            <div class="text-2xl font-bold">{{ dbStats.size || '--' }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">表数量</div>
            <div class="text-2xl font-bold">{{ dbStats.tables ?? '--' }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">活动连接</div>
            <div class="text-2xl font-bold">{{ dbStats.connections ?? '--' }}</div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex gap-2 mb-5 flex-wrap">
          <button @click="backupDatabase" class="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
            备份至 GO 分支
          </button>
          <button @click="restoreDatabase" class="flex items-center gap-2 px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            从 GO 分支恢复
          </button>
          <button @click="clearDbLogs" class="flex items-center gap-2 px-4 py-2 bg-red-900/30 hover:bg-red-900/50 text-red-300 rounded-lg text-sm">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
            清空 GO 服务器日志表
          </button>
          <button @click="loadDbStats" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">刷新统计</button>
        </div>

        <!-- 数据表列表 -->
        <h3 class="font-semibold text-sm mb-3">数据表列表 (GO 服务器 127.0.0.1:5432)</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-border-primary text-text-tertiary text-xs">
              <th class="text-left py-2.5 px-3">表名</th>
              <th class="text-right py-2.5 px-3">记录数</th>
              <th class="text-right py-2.5 px-3">大小</th>
              <th class="text-right py-2.5 px-3">操作</th>
            </tr></thead>
            <tbody>
              <tr v-if="!dbTables.length">
                <td colspan="4" class="text-center py-6 text-text-tertiary">暂无数据，点击「刷新统计」加载</td>
              </tr>
              <tr v-for="t in dbTables" :key="t.name" class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="py-2.5 px-3 font-mono text-xs">{{ t.name }}</td>
                <td class="py-2.5 px-3 text-right text-text-secondary">{{ t.rows?.toLocaleString() ?? '--' }}</td>
                <td class="py-2.5 px-3 text-right text-text-secondary">{{ t.size || '--' }}</td>
                <td class="py-2.5 px-3 text-right whitespace-nowrap">
                  <button @click="viewTable(t.name)" class="text-xs text-primary hover:text-primary-hover mr-2">查看</button>
                  <button @click="backupTable(t.name)" class="text-xs text-[#f0b90b] hover:text-yellow-400">备份</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ============================  MODALS  ============================ -->

    <!-- Role Modal -->
    <div v-if="showRoleModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showRoleModal=false">
      <div class="bg-dark-100 rounded-2xl p-6 w-full max-w-md border border-border-primary">
        <h3 class="text-base font-bold mb-4">{{ editingRoleId ? '编辑角色' : '新增角色' }}</h3>
        <div class="space-y-3">
          <div>
            <label class="block text-xs text-text-secondary mb-1">角色名称 *</label>
            <input v-model="roleForm.role_name" type="text" placeholder="如：系统管理员"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">角色代码 *</label>
            <input v-model="roleForm.role_code" type="text" placeholder="如：sys_admin" :disabled="!!editingRoleId"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary disabled:opacity-50" />
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">描述</label>
            <textarea v-model="roleForm.description" rows="2" placeholder="角色描述"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary resize-none"></textarea>
          </div>
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" v-model="roleForm.is_active" class="w-4 h-4 accent-primary" />
            启用此角色
          </label>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showRoleModal=false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">取消</button>
          <button @click="saveRole" class="px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存</button>
        </div>
      </div>
    </div>

    <!-- Permission Modal -->
    <div v-if="showPermModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showPermModal=false">
      <div class="bg-dark-100 rounded-2xl p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto border border-border-primary">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-bold">权限管理 — {{ permRole?.role_name }}</h3>
          <div class="flex gap-2 text-xs">
            <button @click="selectedPerms = allPerms.map(p=>p.permission_id)" class="px-2 py-1 bg-dark-200 rounded">全选</button>
            <button @click="selectedPerms = []" class="px-2 py-1 bg-dark-200 rounded">清空</button>
          </div>
        </div>
        <div class="text-xs text-text-tertiary mb-4">已选择 {{ selectedPerms.length }} 个权限</div>

        <div v-for="group in permGroups" :key="group.type" class="bg-dark-200 rounded-xl p-4 mb-3">
          <h4 class="font-semibold text-sm mb-3">{{ group.label }}</h4>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            <label v-for="p in group.items" :key="p.permission_id" class="flex items-start gap-2 text-xs cursor-pointer">
              <input type="checkbox" :value="p.permission_id" v-model="selectedPerms" class="mt-0.5 accent-primary" />
              <span>
                <div class="font-medium">{{ p.permission_name }}</div>
                <div class="text-text-tertiary">{{ p.description || p.resource_path }}</div>
              </span>
            </label>
          </div>
          <div v-if="!group.items.length" class="text-xs text-text-tertiary text-center py-2">暂无权限</div>
        </div>

        <div class="flex justify-end gap-2 mt-4">
          <button @click="showPermModal=false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">取消</button>
          <button @click="savePermissions" class="px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存权限</button>
        </div>
      </div>
    </div>

    <!-- Security Component Config Modal -->
    <div v-if="showCompConfigModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showCompConfigModal=false">
      <div class="bg-dark-100 rounded-2xl p-6 w-full max-w-xl border border-border-primary">
        <h3 class="text-base font-bold mb-4">组件配置 — {{ currentComp?.component_name||currentComp?.name }}</h3>
        <div class="bg-dark-200 rounded-xl p-3 mb-4 text-xs text-text-secondary">{{ currentComp?.description || '无描述' }}</div>
        <div>
          <label class="block text-xs text-text-secondary mb-1">配置 JSON</label>
          <textarea v-model="compConfigJson" rows="10"
            class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-xs font-mono focus:outline-none focus:border-primary resize-y"
            placeholder='{"key": "value"}'></textarea>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button @click="showCompConfigModal=false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">取消</button>
          <button @click="saveCompConfig" class="px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存</button>
        </div>
      </div>
    </div>

    <!-- Security Component Logs Modal -->
    <div v-if="showCompLogsModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showCompLogsModal=false">
      <div class="bg-dark-100 rounded-2xl p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto border border-border-primary">
        <h3 class="text-base font-bold mb-4">操作日志 — {{ currentComp?.component_name||currentComp?.name }}</h3>
        <table class="w-full text-xs">
          <thead><tr class="border-b border-border-primary text-text-tertiary">
            <th class="text-left py-2 px-2">时间</th>
            <th class="text-left py-2 px-2">操作</th>
            <th class="text-left py-2 px-2">结果</th>
            <th class="text-left py-2 px-2">操作者</th>
            <th class="text-left py-2 px-2">IP</th>
          </tr></thead>
          <tbody>
            <tr v-for="log in compLogs" :key="log.log_id" class="border-b border-border-secondary hover:bg-dark-50">
              <td class="py-2 px-2 text-text-tertiary">{{ fmtDate(log.performed_at) }}</td>
              <td class="py-2 px-2">{{ log.action }}</td>
              <td class="py-2 px-2" :class="log.result==='success' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                {{ log.result==='success' ? '成功' : '失败' }}
              </td>
              <td class="py-2 px-2 text-text-tertiary">{{ log.performed_by || '--' }}</td>
              <td class="py-2 px-2 font-mono text-text-tertiary">{{ log.ip_address || '--' }}</td>
            </tr>
            <tr v-if="!compLogs.length"><td colspan="5" class="text-center py-6 text-text-tertiary">暂无日志</td></tr>
          </tbody>
        </table>
        <div class="flex justify-end mt-4">
          <button @click="showCompLogsModal=false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">关闭</button>
        </div>
      </div>
    </div>

    <!-- Log Detail Modal -->
    <div v-if="showLogDetailModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showLogDetailModal=false">
      <div class="bg-dark-100 rounded-2xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto border border-border-primary">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-bold">日志详情</h3>
          <button @click="showLogDetailModal=false" class="text-text-tertiary hover:text-text-primary text-xl leading-none">&times;</button>
        </div>
        <div v-if="selectedLog" class="space-y-3 text-sm">
          <div class="grid grid-cols-2 gap-3">
            <div><label class="block text-xs text-text-tertiary mb-0.5">日志ID</label><div>{{ selectedLog.log_id }}</div></div>
            <div><label class="block text-xs text-text-tertiary mb-0.5">时间</label><div>{{ fmtDate(selectedLog.timestamp||selectedLog.time) }}</div></div>
            <div>
              <label class="block text-xs text-text-tertiary mb-0.5">级别</label>
              <span :class="getLogLevelClass(selectedLog.level)" class="px-2 py-0.5 rounded text-xs font-bold">{{ (selectedLog.level||'').toUpperCase() }}</span>
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-0.5">分类</label>
              <span :class="getLogCatClass(selectedLog.category)" class="px-2 py-0.5 rounded text-xs">{{ getLogCatLabel(selectedLog.category) }}</span>
            </div>
            <div><label class="block text-xs text-text-tertiary mb-0.5">用户</label><div>{{ selectedLog.user_id || 'System' }}</div></div>
          </div>
          <div><label class="block text-xs text-text-tertiary mb-0.5">消息</label><div>{{ selectedLog.message }}</div></div>
          <div v-if="selectedLog.details">
            <label class="block text-xs text-text-tertiary mb-0.5">详细信息</label>
            <pre class="bg-dark-300 p-3 rounded text-xs overflow-x-auto">{{ JSON.stringify(selectedLog.details, null, 2) }}</pre>
          </div>
        </div>
        <div class="flex justify-end mt-4">
          <button @click="showLogDetailModal=false" class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">关闭</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '@/services/api.js'
import dayjs from 'dayjs'

// ── Toast ──────────────────────────────────────────────────
const toasts = ref([])
function toast(message, type = 'success') {
  const id = Date.now() + Math.random()
  toasts.value.push({ id, message, type })
  setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id) }, 3000)
}

// ── Tabs ───────────────────────────────────────────────────
const activeTab = ref('version')
const tabs = [
  { id: 'rbac',     label: '角色权限管理' },
  { id: 'push',     label: '实时推送管理' },
  { id: 'notify',   label: '通知服务' },
  { id: 'security', label: '安全组件管理' },
  { id: 'ssl',      label: 'SSL证书管理' },
  { id: 'logs',     label: '系统日志' },
  { id: 'version',  label: '系统版本管理' },
  { id: 'database', label: '数据库管理' },
]

// ── Helpers ────────────────────────────────────────────────
const buildTime = dayjs().format('YYYY-MM-DD HH:mm')
function fmtDate(d) { return d ? dayjs(d).format('YYYY-MM-DD HH:mm:ss') : '--' }
function formatTimeAgo(ts) {
  const sec = Math.floor((Date.now() - ts) / 1000)
  if (sec < 60) return `${sec}s前`
  const min = Math.floor(sec / 60)
  return min < 60 ? `${min}m前` : `${Math.floor(min/60)}h前`
}

// ════════════════════════════════════════════
// ① RBAC 角色权限
// ════════════════════════════════════════════
const roles = ref([])
const rbacFilter = ref('all')
const rbacTypeFilters = [
  { val: 'all', label: '全部' },
  { val: 'active', label: '启用' },
  { val: 'inactive', label: '禁用' },
]
const filteredRoles = computed(() => {
  if (rbacFilter.value === 'active') return roles.value.filter(r => r.is_active !== false)
  if (rbacFilter.value === 'inactive') return roles.value.filter(r => r.is_active === false)
  return roles.value
})

const showRoleModal = ref(false)
const editingRoleId = ref(null)
const roleForm = ref({ role_name: '', role_code: '', description: '', is_active: true })

async function loadRoles() {
  try { const r = await api.get('/api/v1/rbac/roles'); roles.value = r.data || [] } catch {}
}
function openAddRole() {
  editingRoleId.value = null
  roleForm.value = { role_name: '', role_code: '', description: '', is_active: true }
  showRoleModal.value = true
}
function openEditRole(role) {
  editingRoleId.value = role.role_id || role.id
  roleForm.value = { role_name: role.role_name, role_code: role.role_code, description: role.description || '', is_active: role.is_active !== false }
  showRoleModal.value = true
}
async function saveRole() {
  try {
    if (editingRoleId.value) {
      await api.put(`/api/v1/rbac/roles/${editingRoleId.value}`, roleForm.value)
      toast('角色更新成功')
    } else {
      await api.post('/api/v1/rbac/roles', roleForm.value)
      toast('角色创建成功')
    }
    showRoleModal.value = false
    await loadRoles()
  } catch (e) { toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function deleteRole(role) {
  if (!confirm(`确认删除角色「${role.role_name}」？`)) return
  try {
    await api.delete(`/api/v1/rbac/roles/${role.role_id || role.id}`)
    toast('角色已删除'); await loadRoles()
  } catch (e) { toast('删除失败', 'error') }
}

// Permission Modal
const showPermModal = ref(false)
const permRole = ref(null)
const allPerms = ref([])
const selectedPerms = ref([])
const permGroups = computed(() => [
  { type: 'api',    label: 'API接口权限',   items: allPerms.value.filter(p => p.resource_type === 'api') },
  { type: 'menu',   label: '菜单导航权限',  items: allPerms.value.filter(p => p.resource_type === 'menu') },
  { type: 'button', label: '按钮操作权限',  items: allPerms.value.filter(p => p.resource_type === 'button') },
])
async function openRolePermissions(role) {
  permRole.value = role
  try {
    const [allR, roleR] = await Promise.all([
      api.get('/api/v1/rbac/permissions'),
      api.get(`/api/v1/rbac/roles/${role.role_id || role.id}`),
    ])
    allPerms.value = allR.data || []
    const assigned = roleR.data?.permissions || []
    selectedPerms.value = assigned.map(p => p.permission_id || p)
  } catch { allPerms.value = []; selectedPerms.value = [] }
  showPermModal.value = true
}
async function savePermissions() {
  try {
    await api.post(`/api/v1/rbac/roles/${permRole.value.role_id || permRole.value.id}/permissions`,
      { permission_ids: selectedPerms.value })
    toast('权限保存成功')
    showPermModal.value = false
    await loadRoles()
  } catch (e) { toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// ════════════════════════════════════════════
// ② 实时推送管理 — 数据源: GET /api/v1/ws/stats + POST /api/v1/ws/config
// ════════════════════════════════════════════
const STREAMER_LABELS = { market_data: '市场数据', account_balance: '账户余额', risk_metrics: '风险指标', mt5_connection: 'MT5连接状态' }
const STREAMER_ADJUST_CONFIGS = [
  { name: 'market_data', label: '市场数据推送', min: 0.1, max: 10, options: [
    { value: 0.25, label: '0.25s (高频)' }, { value: 0.5, label: '0.5s' }, { value: 1, label: '1s (默认)' }, { value: 2, label: '2s' }, { value: 5, label: '5s (低频)' }] },
  { name: 'account_balance', label: '账户余额推送', min: 5, max: 60, options: [
    { value: 5, label: '5s' }, { value: 10, label: '10s' }, { value: 30, label: '30s (默认)' }, { value: 60, label: '60s' }] },
  { name: 'risk_metrics', label: '风险指标推送', min: 10, max: 120, options: [
    { value: 10, label: '10s' }, { value: 30, label: '30s (默认)' }, { value: 60, label: '60s' }, { value: 120, label: '120s' }] },
  { name: 'mt5_connection', label: 'MT5连接状态', min: 10, max: 120, options: [
    { value: 10, label: '10s' }, { value: 30, label: '30s (默认)' }, { value: 60, label: '60s' }, { value: 120, label: '120s' }] },
]
const REDIS_CHANNELS = [
  { channel: 'ws:broadcast',       desc: '通用广播（策略/持仓）' },
  { channel: 'ws:market_data',     desc: '市场行情数据' },
  { channel: 'ws:account_balance', desc: '账户余额更新' },
  { channel: 'ws:risk_metrics',    desc: '风险指标' },
  { channel: 'ws:order_update',    desc: '订单成交事件' },
  { channel: 'ws:position_update', desc: '持仓变化' },
]

const pushStreamers = ref({})
const pushConnections = ref(0)
const pushServerTime = ref('--')
const pushNewIntervals = ref({ market_data: 1, account_balance: 30, risk_metrics: 30, mt5_connection: 30 })
const pushApplying = ref({})

async function loadPushData() {
  try {
    const r = await api.get('/api/v1/ws/stats')
    const d = r.data
    pushStreamers.value = d.streamers || {}
    pushConnections.value = d.connections?.total ?? 0
    pushServerTime.value = d.server_time ? new Date(d.server_time).toLocaleString('zh-CN') : '--'
    // Sync dropdown values to current intervals
    for (const name of Object.keys(pushNewIntervals.value)) {
      const ms = d.streamers?.[name]?.interval_ms
      if (ms) pushNewIntervals.value[name] = ms / 1000
    }
  } catch {}
}

async function applyFrequency(streamerName) {
  pushApplying.value[streamerName] = true
  try {
    await api.post('/api/v1/ws/config', { streamer: streamerName, interval: pushNewIntervals.value[streamerName] })
    toast(`${STREAMER_LABELS[streamerName] || streamerName} 频率已更新`)
    await loadPushData()
  } catch (e) { toast('更新失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { pushApplying.value[streamerName] = false }
}

// ════════════════════════════════════════════
// ③ 通知服务
// ════════════════════════════════════════════
const showAppSecret = ref(false)
const feishuConfig = ref({ app_id: '', app_secret: '' })
const feishuStatus = ref({ connected: false, token_expires_at: null })
const testRecipient = ref('')
const testRecipientManual = ref('')
const notifyUsers = ref([])

const marketClosureConfig = ref({ enabled: true, summer_open: '23:00', summer_close: '22:00', winter_open: '00:00', winter_close: '23:00' })
const marketStatus = ref({ is_open: false })

const templateCategories = [
  { val: '', label: '全部' },
  { val: 'trade', label: '交易类' },
  { val: 'risk', label: '风险类' },
  { val: 'system', label: '系统类' },
]
const templateCategoryFilter = ref('')
const templates = ref([])
const filteredTemplates = computed(() => {
  if (!templateCategoryFilter.value) return templates.value
  return templates.value.filter(t => t.category === templateCategoryFilter.value)
})
const editDialogVisible = ref(false)
const editingTemplate = ref(null)
const availableSounds = ref([])

const notifyLogFilters = ref({ service_type: '', status: '' })
const notifyLogs = ref([])

const sounds = ref([])
const selectedSoundFile = ref(null)
const soundUploading = ref(false)
const soundFileInput = ref(null)

function getCategoryClass(cat) {
  return { trade: 'bg-blue-500/20 text-blue-400', risk: 'bg-[#f6465d]/20 text-[#f6465d]', system: 'bg-purple-500/20 text-purple-400' }[cat] || 'bg-dark-300 text-text-secondary'
}
function getCategoryLabel(cat) {
  return { trade: '交易类', risk: '风险类', system: '系统类' }[cat] || (cat || '其他')
}
function getPriorityClass(p) {
  return { 1: 'bg-dark-300 text-text-secondary', 2: 'bg-blue-500/20 text-blue-400', 3: 'bg-yellow-500/20 text-yellow-400', 4: 'bg-[#f6465d]/20 text-[#f6465d]' }[p] || 'bg-dark-300 text-text-secondary'
}
function getPriorityLabel(p) {
  return { 1: '低', 2: '中', 3: '高', 4: '紧急' }[p] || String(p || '--')
}
function formatFileSize(bytes) {
  if (!bytes) return '--'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

async function loadFeishuConfig() {
  try {
    const r = await api.get('/api/v1/notifications/config')
    const cfg = (r.data.configs || []).find(c => c.service_type === 'feishu')
    if (cfg) {
      feishuConfig.value.app_id = cfg.config_data?.app_id || ''
      feishuConfig.value.app_secret = cfg.config_data?.app_secret || ''
    }
  } catch {}
}
async function checkFeishuStatus() {
  try {
    const r = await api.get('/api/v1/notifications/feishu/status')
    feishuStatus.value = r.data
  } catch { feishuStatus.value = { connected: false } }
}
async function saveFeishuConfig() {
  try {
    await api.put('/api/v1/notifications/config/feishu', { is_enabled: true, config_data: feishuConfig.value })
    toast('飞书配置已保存')
  } catch (e) { toast('保存失败', 'error') }
}
async function sendTestNotification() {
  const recipient = testRecipient.value || testRecipientManual.value
  try {
    await api.post(`/api/v1/notifications/test/feishu${recipient ? '?recipient=' + encodeURIComponent(recipient) : ''}`)
    toast('测试通知已发送')
  } catch (e) { toast('发送失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function loadNotifyUsers() {
  try {
    const r = await api.get('/api/v1/users')
    notifyUsers.value = r.data.users || r.data || []
  } catch {}
}

async function loadMarketClosureConfig() {
  try {
    const r = await api.get('/api/v1/system/market-closure-config')
    const cfg = r.data.config || r.data
    marketClosureConfig.value = { ...marketClosureConfig.value, ...cfg }
  } catch {}
}
async function loadMarketStatus() {
  try {
    const r = await api.get('/api/v1/system/market-status')
    marketStatus.value = r.data
  } catch {}
}
async function saveMarketClosureConfig() {
  try {
    await api.put('/api/v1/system/market-closure-config', marketClosureConfig.value)
    toast('停市配置已保存')
  } catch (e) { toast('保存失败', 'error') }
}

async function loadTemplates() {
  try {
    const r = await api.get('/api/v1/notifications/templates' + (templateCategoryFilter.value ? '?category=' + templateCategoryFilter.value : ''))
    templates.value = (r.data.templates || r.data || []).map(t => ({
      ...t,
      alert_sound_file: t.alert_sound_file || t.alert_sound || '',
      alert_sound_repeat: t.alert_sound_repeat || t.repeat_count || 1,
      is_enabled: t.is_enabled ?? t.is_active ?? true,
    }))
  } catch {}
}
async function toggleTemplate(tpl) {
  tpl.is_enabled = !tpl.is_enabled
  try {
    await api.put(`/api/v1/notifications/templates/${tpl.template_id}`, { is_enabled: tpl.is_enabled })
  } catch { tpl.is_enabled = !tpl.is_enabled }
}
function openEditTemplate(tpl) {
  editingTemplate.value = JSON.parse(JSON.stringify(tpl))
  editDialogVisible.value = true
}
async function saveTemplate() {
  try {
    await api.put(`/api/v1/notifications/templates/${editingTemplate.value.template_id}`, editingTemplate.value)
    const idx = templates.value.findIndex(t => t.template_id === editingTemplate.value.template_id)
    if (idx !== -1) templates.value[idx] = { ...editingTemplate.value }
    editDialogVisible.value = false
    toast('模板已保存')
  } catch (e) { toast('保存失败', 'error') }
}
async function sendTestTemplate(tpl) {
  try {
    const recipient = testRecipient.value || testRecipientManual.value
    if (recipient) {
      // Use the test/feishu endpoint for direct recipient
      await api.post(`/api/v1/notifications/test/feishu?recipient=${encodeURIComponent(recipient)}`)
    } else {
      // Use send endpoint with correct schema
      // Get current admin user_id from users list
      const adminUser = notifyUsers.value.find(u => u.role === '管理员') || notifyUsers.value[0]
      if (!adminUser) { toast('请先选择接收人', 'error'); return }
      await api.post('/api/v1/notifications/send', {
        template_key: tpl.template_key || tpl.template_code || tpl.template_name,
        user_ids: [adminUser.user_id || adminUser.id],
        variables: {}
      })
    }
    toast('测试通知已发送')
  } catch (e) { toast('发送失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

async function loadNotifyLogs() {
  try {
    const params = new URLSearchParams()
    if (notifyLogFilters.value.service_type) params.append('service_type', notifyLogFilters.value.service_type)
    if (notifyLogFilters.value.status) params.append('status', notifyLogFilters.value.status)
    params.append('limit', '50')
    const r = await api.get('/api/v1/notifications/logs?' + params.toString())
    notifyLogs.value = r.data.logs || r.data || []
  } catch {}
}

async function loadSounds() {
  try {
    const r = await api.get('/api/v1/sounds')
    sounds.value = r.data.sounds || r.data || []
    availableSounds.value = sounds.value
  } catch {}
}
function onSoundFileSelected(e) {
  selectedSoundFile.value = e.target.files[0] || null
}
async function uploadSoundFile() {
  if (!selectedSoundFile.value) return
  soundUploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', selectedSoundFile.value)
    await api.post('/api/v1/sounds/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    toast('上传成功'); selectedSoundFile.value = null
    if (soundFileInput.value) soundFileInput.value.value = ''
    await loadSounds()
  } catch (e) { toast('上传失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { soundUploading.value = false }
}
async function importExistingSounds() {
  try {
    await api.post('/api/v1/sounds/import-existing')
    toast('导入成功'); await loadSounds()
  } catch (e) { toast('导入失败', 'error') }
}
async function syncSoundsToFeishu() {
  try {
    await api.post('/api/v1/sounds/sync-to-feishu')
    toast('同步成功'); await loadSounds()
  } catch (e) { toast('同步失败', 'error') }
}
function playSound(filename) {
  const baseUrl = api.defaults?.baseURL || ''
  const audio = new Audio(`${baseUrl}/sounds/${filename}`)
  audio.play().catch(() => toast('播放失败', 'error'))
}
async function deleteSound(filename) {
  try {
    await api.delete(`/api/v1/sounds/${filename}`)
    toast('已删除'); await loadSounds()
  } catch (e) { toast('删除失败', 'error') }
}

async function initNotifyTab() {
  await Promise.all([
    loadFeishuConfig(), checkFeishuStatus(), loadNotifyUsers(),
    loadMarketClosureConfig(), loadMarketStatus(),
    loadTemplates(), loadNotifyLogs(), loadSounds(),
  ])
}

// ════════════════════════════════════════════
// ④ 安全组件管理
// ════════════════════════════════════════════
const securityComponents = ref([])
const securityFilter = ref('all')
const securityTypeFilters = [
  { val: 'all', label: '全部' },
  { val: 'middleware', label: '中间件' },
  { val: 'service', label: '服务' },
  { val: 'protection', label: '防护' },
]
const filteredSecurityComponents = computed(() => {
  if (securityFilter.value === 'all') return securityComponents.value
  return securityComponents.value.filter(c => (c.component_type || c.type) === securityFilter.value)
})

const showCompConfigModal = ref(false)
const showCompLogsModal = ref(false)
const currentComp = ref(null)
const compLogs = ref([])
const compConfigJson = ref('{}')

function getCompTypeClass(t) {
  return { middleware: 'bg-blue-500/20 text-blue-400', service: 'bg-purple-500/20 text-purple-400', protection: 'bg-[#0ecb81]/20 text-[#0ecb81]' }[t] || 'bg-dark-300 text-text-secondary'
}
function getCompTypeLabel(t) {
  return { middleware: '中间件', service: '服务', protection: '防护' }[t] || (t || '未知')
}

async function loadSecurityComponents() {
  try {
    const r = await api.get('/api/v1/security/components')
    securityComponents.value = r.data || []
  } catch {
    // Fallback static data
    securityComponents.value = [
      { component_id: 1, component_name: 'JWT 验证', component_code: 'jwt_auth', component_type: 'middleware', description: '对所有 API 请求进行 JWT Token 校验', is_enabled: true, status: 'normal', priority: 1 },
      { component_id: 2, component_name: 'CORS 防护', component_code: 'cors',     component_type: 'protection', description: '限制跨域请求来源', is_enabled: true, status: 'normal', priority: 2 },
      { component_id: 3, component_name: '速率限制', component_code: 'rate_limit', component_type: 'protection', description: '限制单 IP 每分钟请求次数', is_enabled: true, status: 'normal', priority: 3 },
      { component_id: 4, component_name: 'HTTPS 强制', component_code: 'https',   component_type: 'middleware', description: '强制所有请求使用 HTTPS', is_enabled: true, status: 'normal', priority: 4 },
    ]
  }
}
async function enableComponent(comp) {
  try {
    await api.post(`/api/v1/security/components/${comp.component_id || comp.name}/enable`, { force: false })
    comp.is_enabled = true; comp.enabled = true; toast('已启用')
  } catch (e) { toast('操作失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function disableComponent(comp) {
  try {
    await api.post(`/api/v1/security/components/${comp.component_id || comp.name}/disable`, { force: false })
    comp.is_enabled = false; comp.enabled = false; toast('已禁用')
  } catch (e) { toast('操作失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
function openCompConfig(comp) {
  currentComp.value = comp
  compConfigJson.value = JSON.stringify(comp.config_json || comp.config || {}, null, 2)
  showCompConfigModal.value = true
}
async function saveCompConfig() {
  try {
    const cfg = JSON.parse(compConfigJson.value)
    await api.put(`/api/v1/security/components/${currentComp.value.component_id || currentComp.value.name}/config`, { config_json: cfg })
    toast('配置已保存'); showCompConfigModal.value = false
  } catch (e) { toast('保存失败: ' + e.message, 'error') }
}
async function viewCompLogs(comp) {
  currentComp.value = comp
  try {
    const r = await api.get(`/api/v1/security/components/${comp.component_id || comp.name}/logs`)
    compLogs.value = r.data || []
  } catch { compLogs.value = [] }
  showCompLogsModal.value = true
}

// ════════════════════════════════════════════
// ⑤ SSL 证书
// ════════════════════════════════════════════
const allCerts = ref([])
const currentCert = ref(null)
const sslCerts = ref([])

function getCertStatusClass(s) {
  return { healthy: 'bg-[#0ecb81]/20 text-[#0ecb81]', warning: 'bg-[#f0b90b]/20 text-[#f0b90b]', critical: 'bg-[#f6465d]/20 text-[#f6465d]', expired: 'bg-[#f6465d]/20 text-[#f6465d]' }[s] || 'bg-dark-200 text-text-secondary'
}
function getCertStatusText(s) {
  return { healthy: '正常', warning: '即将过期', critical: '紧急', expired: '已过期', error: '错误' }[s] || s
}
function getDaysClass(d) {
  if (d <= 7) return 'text-[#f6465d]'; if (d <= 30) return 'text-[#f0b90b]'; return 'text-[#0ecb81]'
}
function certStatusClass(cert) {
  const exp = dayjs(cert.expires_at || cert.expiry_date)
  const days = exp.diff(dayjs(), 'day')
  if (!exp.isValid()) return 'bg-dark-200 text-text-tertiary'
  if (days < 0) return 'bg-[#f6465d]/20 text-[#f6465d]'
  if (days < 30) return 'bg-[#f0b90b]/20 text-[#f0b90b]'
  return 'bg-[#0ecb81]/20 text-[#0ecb81]'
}
function certStatusText(cert) {
  const exp = dayjs(cert.expires_at || cert.expiry_date)
  const days = exp.diff(dayjs(), 'day')
  if (!exp.isValid()) return '未知'
  if (days < 0) return '已过期'
  if (days < 30) return `${days}天后过期`
  return `有效 ${days}天`
}
async function loadCurrentCert() {
  // Get live cert status from monitor/status (all 3 certs)
  try {
    const r = await api.get('/api/v1/monitor/status')
    allCerts.value = r.data?.ssl_certificate || []
    currentCert.value = allCerts.value.length ? allCerts.value[0] : { exists: false }
  } catch (e) { allCerts.value = []; currentCert.value = { exists: false, error: e.message } }
  // Get DB registered certs
  try { const r = await api.get('/api/v1/ssl/certificates'); sslCerts.value = r.data || [] } catch {}
}

// ════════════════════════════════════════════
// ⑥ 系统日志
// ════════════════════════════════════════════
const systemLogs = ref([])
const logFilters = ref({ level: '', category: '', limit: 100 })
const showLogDetailModal = ref(false)
const selectedLog = ref(null)

function getLogLevelClass(l) {
  return { info: 'bg-primary/20 text-primary', warning: 'bg-[#f0b90b]/20 text-[#f0b90b]', error: 'bg-[#f6465d]/20 text-[#f6465d]', critical: 'bg-[#f6465d]/20 text-[#f6465d]' }[l] || 'bg-dark-200 text-text-secondary'
}
function getLogCatClass(c) {
  return { api: 'bg-blue-500/20 text-blue-400', trade: 'bg-[#0ecb81]/20 text-[#0ecb81]', system: 'bg-purple-500/20 text-purple-400', auth: 'bg-[#f0b90b]/20 text-[#f0b90b]' }[c] || 'bg-dark-200 text-text-secondary'
}
function getLogCatLabel(c) {
  return { api: 'API', trade: '交易', system: '系统', auth: '认证' }[c] || (c || '--')
}
async function loadSystemLogs() {
  const params = {}
  if (logFilters.value.level) params.level = logFilters.value.level
  if (logFilters.value.category) params.category = logFilters.value.category
  params.limit = logFilters.value.limit
  try {
    const r = await api.get('/api/v1/system/logs', { params })
    systemLogs.value = r.data?.logs || r.data || []
  } catch { systemLogs.value = [] }
}
async function clearOldLogs() {
  if (!confirm('确认清理7天前的旧日志？此操作不可恢复！')) return
  try { await api.delete('/api/v1/system/logs/old'); toast('旧日志已清理'); await loadSystemLogs() }
  catch (e) { toast('清理失败', 'error') }
}
function openLogDetail(log) { selectedLog.value = log; showLogDetailModal.value = true }

// ════════════════════════════════════════════
// ⑦ 版本管理
// ════════════════════════════════════════════
const sysInfo = ref({})
const versionHistory = ref([])
const pushRemark = ref('')
const pushing = ref(false)

async function loadSysInfo() {
  try { const r = await api.get('/api/v1/system/info'); sysInfo.value = r.data || {} } catch {}
}
async function refreshVersionHistory() {
  try { const r = await api.get('/api/v1/system/github/versions'); versionHistory.value = r.data || [] }
  catch { versionHistory.value = [] }
}
async function pushToGitHub() {
  pushing.value = true
  try {
    await api.post('/api/v1/system/github/push', { remark: pushRemark.value, branch: 'GO', repo: 'https://github.com/joycar2010/hustle2026.git' })
    toast('已推送至 GitHub GO 分支')
    await refreshVersionHistory()
  } catch (e) { toast('推送失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { pushing.value = false }
}
async function rollback(hash) {
  if (!confirm(`确认回滚至版本 ${hash.substring(0,7)}？`)) return
  try { await api.post('/api/v1/system/github/rollback', { hash, branch: 'GO' }); toast('回滚成功，请重启服务') }
  catch { toast('回滚失败', 'error') }
}
async function deleteVersion(hash) {
  if (!confirm(`确认从 GO 分支删除版本 ${hash.substring(0,7)}？`)) return
  try { await api.delete(`/api/v1/system/github/backup/${hash}`); toast('版本已删除'); await refreshVersionHistory() }
  catch { toast('删除失败', 'error') }
}

// ════════════════════════════════════════════
// ⑧ 数据库管理
// ════════════════════════════════════════════
const dbStats = ref({ size: null, tables: null, connections: null })
const dbTables = ref([])

async function loadDbStats() {
  try {
    const r = await api.get('/api/v1/system/database/stats')
    const d = r.data || {}
    dbStats.value = {
      size: d.stats?.size || '--',
      tables: d.stats?.tables ?? '--',
      connections: d.stats?.connections ?? '--',
    }
    dbTables.value = d.tables || []
  } catch {}
}
async function backupDatabase() {
  try {
    await api.post('/api/v1/system/database/backup', { target: 'github', branch: 'GO', repo: 'https://github.com/joycar2010/hustle2026.git' })
    toast('数据库备份已提交至 GO 分支')
  } catch (e) { toast('备份失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function restoreDatabase() {
  // Get latest backup filename
  let filename = ''
  try {
    const r = await api.get('/api/v1/system/database/stats')
    // backups are listed in the response or we prompt user
  } catch {}
  filename = prompt('请输入要恢复的备份文件名（如 backup_20260403_223909_UTC.sql）：')
  if (!filename || !filename.trim()) return
  if (!confirm(`确认从备份文件「${filename}」恢复数据库？当前数据将被覆盖！`)) return
  try {
    await api.post('/api/v1/system/database/restore', { filename: filename.trim() })
    toast('数据库恢复成功')
  } catch (e) { toast('恢复失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function clearDbLogs() {
  if (!confirm('确认清空 GO 服务器 PostgreSQL 日志表？此操作不可恢复！')) return
  try { await api.post('/api/v1/system/database/clean-logs'); toast('GO 服务器日志表已清空') }
  catch (e) { toast('清空失败', 'error') }
}
async function viewTable(name) {
  toast(`正在加载表「${name}」数据...`)
}
async function backupTable(name) {
  try {
    await api.post(`/api/v1/system/database/backup-table/${name}`)
    toast(`表「${name}」已备份`)
  } catch (e) { toast('备份失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// ── INIT ───────────────────────────────────────────────────
onMounted(() => {
  loadRoles()
  loadSysInfo()
  refreshVersionHistory()
  loadDbStats()
  loadCurrentCert()
  loadSystemLogs()
  loadSecurityComponents()
  initNotifyTab()
})

watch(activeTab, (tab) => {
  if (tab === 'notify') initNotifyTab()
  if (tab === 'push') loadPushData()
})
</script>

<style scoped>
.card { @apply bg-dark-100 rounded-2xl border border-border-primary p-6; }
</style>
