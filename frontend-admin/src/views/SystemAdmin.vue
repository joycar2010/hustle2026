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
        <h2 class="text-lg font-bold mb-1">实时推送管理</h2>
        <p class="text-xs text-text-tertiary mb-4">管理 WebSocket 实时推送设置，监控各消息类型的推送频率和状态</p>

        <!-- WS 连接状态 -->
        <div class="bg-dark-200 rounded-xl p-4 mb-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold text-sm">连接状态</h3>
            <div class="flex items-center gap-2">
              <div :class="['w-2.5 h-2.5 rounded-full', pushWsConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
              <span :class="['text-sm font-bold', pushWsConnected ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
                {{ pushWsConnected ? '已连接' : '未连接' }}
              </span>
            </div>
          </div>
          <div class="grid grid-cols-3 gap-3">
            <div class="bg-dark-100 rounded-lg p-3">
              <div class="text-xs text-text-tertiary mb-1">连接时长</div>
              <div class="text-base font-mono font-bold">{{ pushUptime }}</div>
            </div>
            <div class="bg-dark-100 rounded-lg p-3">
              <div class="text-xs text-text-tertiary mb-1">消息总数</div>
              <div class="text-base font-mono font-bold">{{ pushTotalMsgs }}</div>
            </div>
            <div class="bg-dark-100 rounded-lg p-3">
              <div class="text-xs text-text-tertiary mb-1">消息速率</div>
              <div class="text-base font-mono font-bold text-primary">{{ pushMsgRate }}/s</div>
            </div>
          </div>
        </div>

        <!-- 推送频率监控 -->
        <div class="bg-dark-200 rounded-xl p-4 mb-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-semibold text-sm">推送频率监控</h3>
            <button @click="loadPushStreamStats" class="text-xs text-primary hover:text-primary-hover">刷新</button>
          </div>
          <div v-if="!pushStreams.length" class="text-center py-4 text-text-tertiary text-xs">
            加载中...
          </div>
          <div class="space-y-2">
            <div v-for="s in pushStreams" :key="s.type" class="bg-dark-100 rounded-lg p-3">
              <div class="flex items-center justify-between mb-1">
                <div class="flex items-center gap-2 text-sm">
                  <div :class="['w-2 h-2 rounded-full', s.active ? 'bg-[#0ecb81] animate-pulse' : s.running ? 'bg-[#f0b90b]' : 'bg-gray-500']"></div>
                  <span class="font-medium">{{ s.name }}</span>
                  <span class="text-text-tertiary text-[10px] bg-dark-200 px-1.5 py-0.5 rounded">{{ s.source }}</span>
                </div>
                <div class="flex items-center gap-2 text-xs">
                  <span class="text-text-tertiary">服务端: {{ s.serverInterval }}s</span>
                  <span :class="['font-mono font-bold', s.actualInterval > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary']">
                    WS: {{ s.actualInterval > 0 ? s.actualInterval+'ms' : '--' }}
                  </span>
                  <span :class="['px-1.5 py-0.5 rounded text-xs font-bold', getStreamStatusClass(s.status)]">
                    {{ getStreamStatusText(s.status) }}
                  </span>
                </div>
              </div>
              <div class="text-xs text-text-tertiary">{{ s.description }}</div>
              <div class="mt-1 grid grid-cols-2 md:grid-cols-4 gap-1 text-xs text-text-tertiary">
                <span>WS收到: {{ s.count }}</span>
                <span>服务端广播: {{ s.broadcastCount }}</span>
                <span>错误: {{ s.errorCount }}</span>
                <span>最后广播: {{ s.lastReceived ? formatTimeAgo(s.lastReceived) : s.lastBroadcast ? s.lastBroadcast.slice(11,19) : '未收到' }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 推送频率调整（实时生效，调用后端 API） -->
        <div class="bg-dark-200 rounded-xl p-4 mb-4">
          <div class="flex items-center justify-between mb-1">
            <h3 class="font-semibold text-sm">推送频率调整</h3>
            <span class="text-[10px] text-[#0ecb81] bg-[#0ecb81]/10 px-2 py-0.5 rounded">实时生效</span>
          </div>
          <p class="text-xs text-text-tertiary mb-4">调整各 Python 推送流的广播间隔，立即应用到运行中的服务，无需重启</p>
          <div class="space-y-4">
            <div v-for="s in pushStreams.filter(s => s.minInterval !== undefined)" :key="s.type" class="bg-dark-100 rounded-lg p-4">
              <div class="flex items-center justify-between mb-2">
                <div>
                  <div class="font-medium text-sm">{{ s.name }}</div>
                  <div class="text-xs text-text-tertiary">{{ s.description }} · 来源: {{ s.source }}</div>
                </div>
                <div class="text-xs text-text-tertiary text-right">
                  <div>当前: <span class="font-mono font-bold text-primary">{{ s.serverInterval }}s</span></div>
                  <div>范围: {{ s.minInterval }}s – {{ s.maxInterval }}s</div>
                </div>
              </div>
              <div class="flex items-center gap-4">
                <div class="flex-1">
                  <input type="range" v-model.number="s.newInterval"
                    :min="s.minInterval" :max="s.maxInterval" :step="s.step"
                    class="w-full h-1.5 bg-dark-300 rounded appearance-none cursor-pointer accent-primary" />
                  <div class="flex justify-between text-xs text-text-tertiary mt-1">
                    <span>{{ s.minInterval }}s</span>
                    <span class="font-mono font-bold text-primary">{{ s.newInterval?.toFixed ? s.newInterval.toFixed(1) : s.newInterval }}s ({{ s.newInterval > 0 ? (1/s.newInterval).toFixed(1) : '∞' }} 次/s)</span>
                    <span>{{ s.maxInterval }}s</span>
                  </div>
                </div>
                <button @click="applyFrequency(s)" :disabled="s.newInterval===s.serverInterval||s.updating"
                  class="px-3 py-1.5 bg-primary hover:bg-primary-hover disabled:bg-dark-300 disabled:text-text-tertiary disabled:cursor-not-allowed rounded text-sm font-bold transition-colors whitespace-nowrap">
                  {{ s.updating ? '应用中...' : '应用' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 消息类型过滤 -->
        <div class="bg-dark-200 rounded-xl p-4">
          <div class="flex items-center justify-between mb-2">
            <div>
              <h3 class="font-semibold text-sm">消息类型过滤</h3>
              <p class="text-xs text-text-tertiary mt-0.5">控制本页 WebSocket 监听哪些消息类型（客户端过滤）</p>
            </div>
            <button @click="toggleAllMsgTypes" class="text-xs text-primary hover:text-primary-hover">
              {{ allMsgTypesOn ? '全部禁用' : '全部启用' }}
            </button>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div v-for="mt in msgTypeFilters" :key="mt.type"
              class="flex items-center justify-between p-3 bg-dark-100 rounded-lg">
              <div class="flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="font-medium text-sm">{{ mt.name }}</span>
                  <span class="text-[10px] text-text-tertiary bg-dark-200 px-1 rounded">{{ mt.source }}</span>
                </div>
                <div class="text-xs text-text-tertiary">{{ mt.description }}</div>
              </div>
              <div @click="mt.enabled = !mt.enabled; saveMsgTypeFilters()"
                :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors', mt.enabled ? 'bg-primary' : 'bg-gray-600']">
                <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', mt.enabled ? 'translate-x-4' : 'translate-x-0.5']"/>
              </div>
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

      <!-- 邮件 SMTP 配置 -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-bold">邮件 SMTP 配置</h2>
            <p class="text-xs text-text-tertiary mt-0.5">配置 SMTP 服务器，用于向用户邮箱发送告警邮件（模板启用邮件渠道时生效）</p>
          </div>
          <div class="flex items-center gap-2">
            <div :class="['w-2 h-2 rounded-full', emailConfig.is_enabled ? 'bg-[#0ecb81]' : 'bg-gray-500']"></div>
            <span :class="['text-xs font-medium', emailConfig.is_enabled ? 'text-[#0ecb81]' : 'text-text-tertiary']">
              {{ emailConfig.is_enabled ? '已启用' : '未启用' }}
            </span>
            <div @click="emailConfig.is_enabled = !emailConfig.is_enabled"
              :class="['relative w-9 h-5 rounded-full cursor-pointer transition-colors', emailConfig.is_enabled ? 'bg-primary' : 'bg-gray-600']">
              <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', emailConfig.is_enabled ? 'translate-x-4' : 'translate-x-0.5']"/>
            </div>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-xs text-text-secondary mb-1">SMTP 主机</label>
            <input v-model="emailConfig.smtp_host" type="text" placeholder="smtp.gmail.com"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">SMTP 端口</label>
            <input v-model.number="emailConfig.smtp_port" type="number" placeholder="587"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">发件邮箱</label>
            <input v-model="emailConfig.from_email" type="email" placeholder="alerts@example.com"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label class="block text-xs text-text-secondary mb-1">SMTP 用户名</label>
            <input v-model="emailConfig.username" type="text" placeholder="同发件邮箱或留空"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div class="col-span-2">
            <label class="block text-xs text-text-secondary mb-1">SMTP 密码/授权码</label>
            <div class="relative">
              <input v-model="emailConfig.password" :type="showEmailPwd ? 'text' : 'password'"
                placeholder="••••••••••••••••" autocomplete="new-password"
                class="w-full px-3 py-2 pr-9 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
              <button @click="showEmailPwd=!showEmailPwd" class="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-secondary text-xs">
                {{ showEmailPwd ? '隐藏' : '显示' }}
              </button>
            </div>
          </div>
        </div>
        <!-- 邮件群发 -->
        <div class="mt-4 pt-4 border-t border-border-primary">
          <h3 class="text-sm font-semibold mb-3">📧 邮件群发</h3>
          <div class="grid grid-cols-1 gap-3">
            <div>
              <label class="block text-xs text-text-secondary mb-1">收件人（逗号分隔多个邮箱）</label>
              <input v-model="emailBroadcast.recipients" type="text" placeholder="a@example.com, b@example.com"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
            </div>
            <div>
              <label class="block text-xs text-text-secondary mb-1">邮件主题</label>
              <input v-model="emailBroadcast.subject" type="text" placeholder="系统通知"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary" />
            </div>
            <div>
              <label class="block text-xs text-text-secondary mb-1">邮件内容</label>
              <textarea v-model="emailBroadcast.body" rows="3" placeholder="请输入邮件正文..."
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary resize-none"></textarea>
            </div>
          </div>
        </div>
        <div class="flex gap-2 mt-4">
          <button @click="saveEmailConfig" class="px-4 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-sm">保存配置</button>
          <button @click="sendEmailBroadcast" :disabled="!emailConfig.is_enabled" class="px-4 py-1.5 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm disabled:opacity-40 disabled:cursor-not-allowed">发送群发邮件</button>
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
              <label class="block text-xs text-text-secondary mb-1">飞书内容模板 <span class="text-text-tertiary">(飞书/邮件/SMS)</span></label>
              <textarea v-model="editingTemplate.content_template" rows="4"
                class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary resize-none"></textarea>
            </div>
            <div>
              <label class="block text-xs text-text-secondary mb-1">
                弹窗内容模板 <span class="text-text-tertiary">(前端弹窗专用,留空则复用上面的飞书内容模板)</span>
              </label>
              <textarea v-model="editingTemplate.popup_content_template" rows="3"
                placeholder="可使用 {spread} {threshold} {current_asset} 等变量"
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

        <!-- 所有域名证书卡片 -->
        <div v-if="allCerts.length > 1" class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <div v-for="cert in allCerts" :key="cert.cert_path"
            class="bg-dark-200 rounded-xl p-4 border"
            :class="cert.status === 'expired' ? 'border-[#f6465d]/40' : cert.status === 'critical' ? 'border-[#f0b90b]/40' : 'border-border-primary'">
            <div class="flex items-center justify-between mb-2">
              <span class="font-semibold font-mono text-sm truncate" :title="cert.domain_names?.[0]">
                {{ cert.domain_names?.[0] || cert.domain || '--' }}
              </span>
              <span :class="getCertStatusClass(cert.status)" class="px-1.5 py-0.5 rounded text-xs font-bold">
                {{ getCertStatusText(cert.status) }}
              </span>
            </div>
            <div class="space-y-1 text-xs text-text-tertiary">
              <div class="flex justify-between">
                <span>剩余</span>
                <span class="font-mono" :class="getDaysClass(cert.days_remaining)">{{ cert.days_remaining }} 天</span>
              </div>
              <div class="flex justify-between">
                <span>过期</span>
                <span class="text-text-secondary">{{ fmtDate(cert.expires_at) }}</span>
              </div>
              <div class="flex justify-between">
                <span>颁发</span>
                <span class="text-text-secondary">{{ cert.issuer || 'Let\'s Encrypt' }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="currentCert && currentCert.exists" class="space-y-4">
          <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
            <div class="bg-dark-200 rounded-xl p-3">
              <div class="text-xs text-text-tertiary mb-1">证书状态</div>
              <div class="flex items-center gap-2">
                <span :class="getCertStatusClass(currentCert.status)" class="px-2 py-0.5 rounded text-xs font-bold">
                  {{ getCertStatusText(currentCert.status) }}
                </span>
                <span v-if="currentCert.is_valid" class="text-[#0ecb81] text-xs">✓ 有效</span>
                <span v-else class="text-[#f6465d] text-xs">✗ 已过期</span>
              </div>
            </div>
            <div class="bg-dark-200 rounded-xl p-3">
              <div class="text-xs text-text-tertiary mb-1">剩余天数</div>
              <div class="text-xl font-mono font-bold" :class="getDaysClass(currentCert.days_remaining)">
                {{ currentCert.days_remaining }} 天
              </div>
            </div>
            <div class="bg-dark-200 rounded-xl p-3">
              <div class="text-xs text-text-tertiary mb-1">颁发者</div>
              <div class="text-xs break-all text-text-secondary">{{ currentCert.issuer || 'Let\'s Encrypt' }}</div>
            </div>
            <div class="bg-dark-200 rounded-xl p-3">
              <div class="text-xs text-text-tertiary mb-1">域名</div>
              <div v-for="d in (currentCert.domain_names||[])" :key="d" class="text-xs text-primary">{{ d }}</div>
            </div>
            <div class="bg-dark-200 rounded-xl p-3">
              <div class="text-xs text-text-tertiary mb-1">颁发时间</div>
              <div class="text-xs text-text-secondary">{{ fmtDate(currentCert.issued_at) }}</div>
            </div>
            <div class="bg-dark-200 rounded-xl p-3">
              <div class="text-xs text-text-tertiary mb-1">过期时间</div>
              <div class="text-xs" :class="currentCert.days_remaining<=30 ? 'text-[#f0b90b]' : 'text-text-secondary'">
                {{ fmtDate(currentCert.expires_at) }}
              </div>
            </div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-2">证书文件路径</div>
            <div class="space-y-1 text-xs font-mono">
              <div><span class="text-text-tertiary">证书: </span>{{ currentCert.cert_path }}</div>
              <div><span class="text-text-tertiary">私钥: </span>{{ currentCert.key_path }}</div>
            </div>
          </div>
          <div v-if="currentCert.days_remaining<=30" class="bg-[#f0b90b]/10 border border-[#f0b90b] rounded-xl p-4">
            <div class="flex items-start gap-2">
              <span class="text-[#f0b90b] text-lg">⚠</span>
              <div>
                <div class="font-medium text-[#f0b90b] text-sm">证书即将过期</div>
                <div class="text-xs text-text-secondary mt-1">证书将在 {{ currentCert.days_remaining }} 天后过期，请及时续期。</div>
              </div>
            </div>
          </div>
        </div>

        <!-- DB list of SSL certs -->
        <div class="mt-4 space-y-2">
          <h3 class="font-semibold text-sm mb-2">已注册证书</h3>
          <div v-for="cert in sslCerts" :key="cert.id" class="bg-dark-200 rounded-xl p-4 flex items-center justify-between">
            <div>
              <div class="font-semibold font-mono text-sm">{{ cert.domain }}</div>
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
            <div class="text-2xl font-mono font-bold text-primary">v{{ sysInfo.frontend_version || '--' }}</div>
            <div class="text-xs text-text-tertiary mt-1">构建时间: {{ sysInfo.frontend_build_time || buildTime }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">后端版本</div>
            <div class="text-2xl font-mono font-bold text-primary">v{{ sysInfo.backend_version || '--' }}</div>
            <div class="text-xs text-text-tertiary mt-1">Go: {{ sysInfo.go_version || '--' }}</div>
            <div class="text-xs text-text-tertiary">Python: {{ sysInfo.python_version || '--' }}</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">数据库</div>
            <div class="text-lg font-mono font-bold">PostgreSQL {{ sysInfo.db_version || '' }}</div>
            <div class="text-xs text-[#0ecb81] mt-1">● go服务器 127.0.0.1:5432 正常</div>
          </div>
          <div class="bg-dark-200 rounded-xl p-4">
            <div class="text-xs text-text-tertiary mb-1">运行时长</div>
            <div class="text-lg font-mono font-bold">{{ sysInfo.uptime || '--' }}</div>
            <div class="text-xs text-text-tertiary mt-1">启动: {{ sysInfo.start_time || '--' }}</div>
          </div>
        </div>

        <!-- GitHub版本管理 -->
        <div class="bg-dark-200 rounded-xl p-5">
          <h3 class="font-bold mb-1">GitHub 版本备份 (分支: go)</h3>
          <div class="text-xs text-text-tertiary mb-3">
            推送目标: <span class="font-mono text-primary">https://github.com/joycar2010/hustle2026.git @ go</span>
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2 text-text-secondary">推送备注</label>
            <input v-model="pushRemark" type="text" placeholder="v2.0.0 - 功能更新说明（可选）"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded-lg focus:outline-none focus:border-primary text-sm" />
          </div>
          <div class="flex gap-3 mb-3">
            <button @click="pushToGitHub" :disabled="pushing"
              class="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-lg text-sm transition-colors">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
              {{ pushing ? '推送中...' : '推送到 go 分支' }}
            </button>
          </div>
          <!-- 推送进度条 -->
          <div v-if="pushing" class="mb-4">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs text-text-tertiary">{{ pushStage }}</span>
            </div>
            <div class="w-full bg-dark-300 rounded-full h-2">
              <div class="bg-primary h-2 rounded-full transition-all duration-500" :style="{ width: pushProgress + '%' }"></div>
            </div>
          </div>
          <!-- 推送结果提示 -->
          <div v-if="pushResult" class="mb-4 px-4 py-2.5 rounded-lg text-xs" :class="pushResult.ok ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'">
            {{ pushResult.msg }}
          </div>

          <h4 class="font-semibold text-sm mb-3">go 分支备份记录</h4>
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
                <tr v-for="v in pagedVersionHistory" :key="v.hash" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-2.5 px-3 font-mono text-xs text-primary">{{ v.hash?.substring(0,7) }}</td>
                  <td class="py-2.5 px-3 text-text-secondary text-xs">{{ v.message }}</td>
                  <td class="py-2.5 px-3 text-text-tertiary text-xs">{{ fmtUTC(v.date) }}</td>
                  <td class="py-2.5 px-3 text-text-tertiary text-xs">{{ v.author }}</td>
                  <td class="py-2.5 px-3 text-right whitespace-nowrap">
                    <button @click="rollback(v.hash)" :disabled="v._loading" class="text-xs text-[#f0b90b] hover:text-yellow-400 mr-2 disabled:opacity-50">
                      {{ v._rolling ? '回滚中...' : '回滚' }}
                    </button>
                    <button @click="deleteVersion(v.hash)" :disabled="v._loading" class="text-xs text-[#f6465d] hover:text-red-400 disabled:opacity-50">
                      {{ v._deleting ? '删除中...' : '删除' }}
                    </button>
                  </td>
                </tr>
                <tr v-if="!versionHistory.length">
                  <td colspan="5" class="text-center py-6 text-text-tertiary text-sm">暂无备份记录</td>
                </tr>
              </tbody>
            </table>
          </div>
          <!-- 分页 -->
          <div v-if="versionHistory.length > versionPageSize" class="flex items-center justify-between mt-3 px-1">
            <span class="text-xs text-text-tertiary">共 {{ versionHistory.length }} 条，第 {{ versionPage }}/{{ versionTotalPages }} 页</span>
            <div class="flex items-center gap-1">
              <button @click="versionPage = 1" :disabled="versionPage <= 1"
                class="px-2 py-1 text-xs rounded bg-dark-200 hover:bg-dark-50 text-text-secondary disabled:opacity-30 disabled:cursor-not-allowed">首页</button>
              <button @click="versionPage--" :disabled="versionPage <= 1"
                class="px-2 py-1 text-xs rounded bg-dark-200 hover:bg-dark-50 text-text-secondary disabled:opacity-30 disabled:cursor-not-allowed">上一页</button>
              <button @click="versionPage++" :disabled="versionPage >= versionTotalPages"
                class="px-2 py-1 text-xs rounded bg-dark-200 hover:bg-dark-50 text-text-secondary disabled:opacity-30 disabled:cursor-not-allowed">下一页</button>
              <button @click="versionPage = versionTotalPages" :disabled="versionPage >= versionTotalPages"
                class="px-2 py-1 text-xs rounded bg-dark-200 hover:bg-dark-50 text-text-secondary disabled:opacity-30 disabled:cursor-not-allowed">末页</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 数据库管理 ===== -->
    <div v-if="activeTab==='database'" class="space-y-4">
      <div class="card">
        <h2 class="text-lg font-bold mb-4">PostgreSQL 数据库管理 (go服务器)</h2>

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
            备份至 go 分支
          </button>
          <button @click="restoreDatabase" class="flex items-center gap-2 px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded-lg text-sm">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            从 go 分支恢复
          </button>
        </div>

        <!-- 数据表列表 -->
        <h3 class="font-semibold text-sm mb-3">数据表列表 (go 服务器 127.0.0.1:5432)</h3>
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
                <td colspan="4" class="text-center py-6 text-text-tertiary">暂无数据</td>
              </tr>
              <tr v-for="t in dbTables" :key="t.name" class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
                <td class="py-2.5 px-3 font-mono text-xs">{{ t.name }}</td>
                <td class="py-2.5 px-3 text-right text-text-secondary">{{ t.rows?.toLocaleString() ?? '--' }}</td>
                <td class="py-2.5 px-3 text-right text-text-secondary">{{ t.size || '--' }}</td>
                <td class="py-2.5 px-3 text-right whitespace-nowrap">
                  <button @click="viewTable(t.name)" class="text-xs text-primary hover:text-primary-hover">查看</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ============================  MODALS  ============================ -->

    <!-- Table View Modal -->
    <div v-if="showTableViewModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showTableViewModal=false">
      <div class="bg-dark-100 rounded-2xl w-full max-w-5xl max-h-[85vh] flex flex-col border border-border-primary">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between shrink-0">
          <div>
            <h3 class="font-bold">表数据查看 — <span class="font-mono text-primary">{{ tableViewName }}</span></h3>
            <span class="text-xs text-text-tertiary">共 {{ tableViewRows.length }} 条记录（最多显示100条）</span>
          </div>
          <button @click="showTableViewModal=false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <div class="flex-1 overflow-auto p-4">
          <div v-if="tableViewLoading" class="text-center py-12 text-text-tertiary">加载中...</div>
          <div v-else-if="!tableViewColumns.length" class="text-center py-12 text-text-tertiary">暂无数据</div>
          <table v-else class="w-full text-xs border-collapse">
            <thead class="sticky top-0 bg-dark-100 z-10">
              <tr>
                <th v-for="col in tableViewColumns" :key="col.name"
                  class="text-left py-2 px-2 border-b border-border-primary text-text-tertiary font-medium whitespace-nowrap">
                  {{ col.name }}
                  <span class="text-[10px] text-text-tertiary ml-1">({{ col.type }})</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, idx) in tableViewRows" :key="idx" class="border-b border-border-secondary hover:bg-dark-50">
                <td v-for="col in tableViewColumns" :key="col.name"
                  class="py-1.5 px-2 font-mono max-w-[300px] truncate" :title="String(row[col.name] ?? '')">
                  {{ row[col.name] ?? '' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Restore Backup Modal -->
    <div v-if="showRestoreModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showRestoreModal=false">
      <div class="bg-dark-100 rounded-2xl w-full max-w-lg border border-border-primary">
        <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
          <h3 class="font-bold">选择备份文件恢复</h3>
          <button @click="showRestoreModal=false" class="text-text-tertiary hover:text-text-primary text-lg">✕</button>
        </div>
        <div class="p-6">
          <div v-if="restoreLoading" class="text-center py-8 text-text-tertiary">加载备份列表...</div>
          <div v-else-if="!backupFiles.length" class="text-center py-8 text-text-tertiary">暂无备份文件，请先执行备份</div>
          <div v-else class="space-y-2 max-h-[400px] overflow-y-auto">
            <div v-for="b in backupFiles" :key="b.filename"
              class="flex items-center justify-between px-4 py-3 bg-dark-200 rounded-lg hover:bg-dark-50 transition-colors">
              <div>
                <div class="font-mono text-xs text-text-primary">{{ b.filename }}</div>
                <div class="text-[10px] text-text-tertiary mt-0.5">{{ b.created_at }} · {{ b.size }}</div>
              </div>
              <button @click="confirmRestore(b.filename)"
                class="px-3 py-1.5 bg-primary hover:bg-primary-hover text-dark-300 font-semibold rounded-lg text-xs whitespace-nowrap">
                恢复此版本
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

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
function fmtUTC(d) { if (!d) return '--'; return dayjs(d).add(8, 'hour').format('YYYY-MM-DD HH:mm:ss') }
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
      api.get(`/api/v1/rbac/roles/${role.role_id || role.id}/permissions`),
    ])
    allPerms.value = allR.data || []
    const assigned = roleR.data || []
    selectedPerms.value = assigned.map(p => p.permission_id || p)
  } catch { allPerms.value = []; selectedPerms.value = [] }
  showPermModal.value = true
}
async function savePermissions() {
  const roleId = permRole.value.role_id || permRole.value.id
  try {
    // 1. Get current role permissions
    const existing = (await api.get(`/api/v1/rbac/roles/${roleId}/permissions`).catch(() => ({ data: [] }))).data || []
    const existingIds = existing.map(p => p.permission_id || p.id || p)

    // 2. Delete permissions no longer selected
    const toRemove = existingIds.filter(id => !selectedPerms.value.includes(id))
    for (const pid of toRemove) {
      await api.delete(`/api/v1/rbac/roles/${roleId}/permissions/${pid}`).catch(() => {})
    }

    // 3. Add newly selected permissions
    const toAdd = selectedPerms.value.filter(id => !existingIds.includes(id))
    for (const pid of toAdd) {
      await api.post(`/api/v1/rbac/roles/${roleId}/permissions`, { permission_id: pid }).catch(() => {})
    }

    toast('权限保存成功')
    showPermModal.value = false
    await loadRoles()
  } catch (e) { toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error') }
}

// ════════════════════════════════════════════
// ② 实时推送管理
// ════════════════════════════════════════════
const pushWsConnected = ref(false)
const pushUptime = ref('0s')
const pushTotalMsgs = ref(0)
const pushMsgRate = ref(0)

// 从后端加载的推送流状态（真实数据）
const pushStreams = ref([])
// WS 实时接收消息计数（覆盖服务端数据）
const pushMsgCounts = ref({})
const pushMsgTimes = ref({})

// 从 API 加载推送流状态
async function loadPushStreamStats() {
  try {
    const r = await api.get('/api/v1/system/push-streams/stats')
    if (r.data.success) {
      const serverStreams = r.data.streams || []
      pushStreams.value = serverStreams.map(s => ({
        type: s.type,
        name: s.name,
        description: s.description,
        source: s.source,
        serverInterval: s.interval,  // 服务端实际间隔
        expectedInterval: Math.round((s.interval || 1) * 1000), // ms
        actualInterval: 0,           // WS 实测间隔
        active: s.running && (s.broadcast_count || 0) > 0,
        running: s.running,
        broadcastCount: s.broadcast_count || 0,
        errorCount: s.error_count || 0,
        lastBroadcast: s.last_broadcast,
        count: pushMsgCounts.value[s.type] || 0,
        lastReceived: pushMsgTimes.value[s.type] || null,
        status: computeStreamStatus(s),
        // 频率调整参数
        minInterval: s.min_interval,
        maxInterval: s.max_interval,
        step: s.step || 1,
        newInterval: s.interval,
        updating: false,
      }))
    }
  } catch {}
}

function computeStreamStatus(s) {
  if (!s.running) return 'inactive'
  if (s.error_count > 0) return 'error'
  if ((s.broadcast_count || 0) === 0) return 'inactive'
  return 'normal'
}

// 调整频率（调用真实 API）
async function applyFrequency(stream) {
  stream.updating = true
  try {
    const r = await api.post('/api/v1/system/push-streams/update', {
      stream_type: stream.type,
      interval: stream.newInterval
    })
    if (r.data.success) {
      stream.serverInterval = stream.newInterval
      toast(`${stream.name} 频率已更新为 ${stream.newInterval}s`)
      await loadPushStreamStats()
    }
  } catch (e) {
    toast(`更新失败: ${e.response?.data?.detail || e.message}`, 'error')
  } finally {
    stream.updating = false
  }
}

// 消息类型过滤（WS 客户端本地过滤）
const msgTypeFilters = ref([
  { type: 'market_data', name: '市场行情', description: '实时 tick/spread 推送', enabled: true, source: 'Go(250ms)' },
  { type: 'account_balance', name: '账户余额', description: '账户资金变动推送', enabled: true, source: 'Python(30s)' },
  { type: 'position_update', name: '持仓更新', description: 'MT5 持仓实时同步', enabled: true, source: 'Python(1s)' },
  { type: 'risk_metrics', name: '风险指标', description: '风险管理指标推送', enabled: true, source: 'Python(30s)' },
  { type: 'order_update', name: '订单更新', description: '待成交订单状态', enabled: true, source: 'Python(2s)' },
  { type: 'mt5_connection_status', name: 'MT5 连接', description: 'MT5 Bridge 健康状态', enabled: true, source: 'Python(30s)' },
  { type: 'strategy_status', name: '策略状态', description: '策略运行状态推送', enabled: true, source: 'Python' },
  { type: 'risk_alert', name: '风险警报', description: '风险触发警报推送', enabled: true, source: 'Python' },
])
const allMsgTypesOn = computed(() => msgTypeFilters.value.every(m => m.enabled))

function getStreamStatusClass(s) {
  return { normal: 'bg-[#0ecb81]/20 text-[#0ecb81]', warning: 'bg-[#f0b90b]/20 text-[#f0b90b]', error: 'bg-[#f6465d]/20 text-[#f6465d]', inactive: 'bg-dark-200 text-text-tertiary' }[s] || 'bg-dark-200 text-text-tertiary'
}
function getStreamStatusText(s) {
  return { normal: '正常', warning: '警告', error: '异常', inactive: '未活跃' }[s] || s
}
function toggleAllMsgTypes() {
  const next = !allMsgTypesOn.value
  msgTypeFilters.value.forEach(m => m.enabled = next)
  toast('消息类型过滤已更新（客户端过滤）')
}
async function saveMsgTypeFilters() {
  toast('消息类型过滤已更新（客户端过滤）')
}

// ── Push streams live monitoring via WebSocket ──
let pushWs = null
let pushUptimeTimer = null
let pushRateTimer = null
let pushStatsTimer = null
let pushStartTime = null
let pushMsgCountLastSec = 0
const pushMsgTimesLocal = {}

function connectPushWs() {
  if (pushWs && pushWs.readyState === WebSocket.OPEN) return
  const token = localStorage.getItem('admin_token')
  if (!token) return
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/ws?token=${token}`
  try {
    pushWs = new WebSocket(url)
    pushWs.onopen = () => {
      pushWsConnected.value = true
      pushStartTime = Date.now()
      pushTotalMsgs.value = 0
    }
    pushWs.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        pushTotalMsgs.value++
        pushMsgCountLastSec++
        const t = msg.type || 'unknown'
        const now = Date.now()
        if (!pushMsgCounts.value[t]) pushMsgCounts.value[t] = 0
        pushMsgCounts.value[t]++
        const stream = pushStreams.value.find(s => s.type === t)
        if (stream) {
          stream.count++
          stream.active = true
          stream.lastReceived = now
          if (pushMsgTimesLocal[t]) {
            stream.actualInterval = now - pushMsgTimesLocal[t]
            stream.status = stream.actualInterval > 0 && stream.actualInterval < stream.expectedInterval * 3 ? 'normal' : 'warning'
          }
        }
        pushMsgTimesLocal[t] = now
        pushMsgTimes.value[t] = now
      } catch {}
    }
    pushWs.onclose = () => { pushWsConnected.value = false }
    pushWs.onerror = () => { pushWsConnected.value = false }
  } catch {}
}

function disconnectPushWs() {
  if (pushWs) { pushWs.close(); pushWs = null }
  if (pushUptimeTimer) clearInterval(pushUptimeTimer)
  if (pushRateTimer) clearInterval(pushRateTimer)
  if (pushStatsTimer) clearInterval(pushStatsTimer)
  pushUptimeTimer = null
  pushRateTimer = null
  pushStatsTimer = null
}

function startPushTimers() {
  pushUptimeTimer = setInterval(() => {
    if (pushStartTime) {
      const sec = Math.floor((Date.now() - pushStartTime) / 1000)
      pushUptime.value = sec < 60 ? `${sec}s` : sec < 3600 ? `${Math.floor(sec/60)}m ${sec%60}s` : `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`
    }
  }, 1000)
  pushRateTimer = setInterval(() => {
    pushMsgRate.value = pushMsgCountLastSec
    pushMsgCountLastSec = 0
  }, 1000)
  // Poll server-side push stats every 10s
  pushStatsTimer = setInterval(() => loadPushStreamStats(), 10000)
}

// ════════════════════════════════════════════
// ③ 通知服务
// ════════════════════════════════════════════
const showAppSecret = ref(false)
const showEmailPwd = ref(false)
const feishuConfig = ref({ app_id: '', app_secret: '' })
const emailConfig = ref({ smtp_host: '', smtp_port: 587, from_email: '', username: '', password: '', is_enabled: false })
const emailBroadcast = ref({ recipients: '', subject: '系统通知', body: '' })
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
    const cfgs = r.data.configs || []
    const feishu = cfgs.find(c => c.service_type === 'feishu')
    if (feishu) {
      feishuConfig.value.app_id = feishu.config_data?.app_id || ''
      feishuConfig.value.app_secret = feishu.config_data?.app_secret || ''
    }
    const email = cfgs.find(c => c.service_type === 'email')
    if (email) {
      emailConfig.value = {
        smtp_host: email.config_data?.smtp_host || '',
        smtp_port: email.config_data?.smtp_port || 587,
        from_email: email.config_data?.from_email || '',
        username: email.config_data?.username || '',
        password: email.config_data?.password || '',
        is_enabled: email.is_enabled || false,
      }
    }
  } catch {}
}
async function saveEmailConfig() {
  try {
    await api.put('/api/v1/notifications/config/email', {
      is_enabled: emailConfig.value.is_enabled,
      config_data: {
        smtp_host: emailConfig.value.smtp_host,
        smtp_port: emailConfig.value.smtp_port,
        from_email: emailConfig.value.from_email,
        username: emailConfig.value.username,
        password: emailConfig.value.password,
      }
    })
    toast('邮件 SMTP 配置已保存')
  } catch (e) { toast('保存失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function sendEmailBroadcast() {
  if (!emailBroadcast.value.recipients || !emailBroadcast.value.subject || !emailBroadcast.value.body) {
    toast('请填写收件人、主题和内容', 'error'); return
  }
  try {
    await api.post('/api/v1/notifications/email/broadcast', {
      recipients: emailBroadcast.value.recipients.split(',').map(s => s.trim()).filter(Boolean),
      subject: emailBroadcast.value.subject,
      body: emailBroadcast.value.body,
    })
    toast('群发邮件已发送')
  } catch (e) { toast('发送失败: ' + (e.response?.data?.detail || e.message), 'error') }
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
  } catch (e) {
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : (Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ') : e.message)
    toast('发送失败: ' + msg, 'error')
  }
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
    if (!recipient) {
      toast('请先选择或输入测试接收人', 'error')
      return
    }
    const channels = []
    if (tpl.enable_feishu) channels.push('feishu')
    if (tpl.enable_email) channels.push('email')
    if (tpl.enable_sms) channels.push('sms')
    const serviceType = channels[0] || 'feishu'
    await api.post(`/api/v1/notifications/test/${serviceType}?recipient=${encodeURIComponent(recipient)}`)
    toast('测试通知已发送')
  } catch (e) {
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : (Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ') : e.message)
    toast('发送失败: ' + msg, 'error')
  }
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
async function playSound(filename) {
  try {
    // /sounds/ is a static mount served by Python backend, no auth required
    const audio = new Audio(`/sounds/${encodeURIComponent(filename)}`)
    audio.crossOrigin = 'anonymous'
    await audio.play()
  } catch (e) {
    // Fallback: fetch with auth as blob
    try {
      const r = await api.get(`/sounds/${encodeURIComponent(filename)}`, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const audio = new Audio(url)
      await audio.play()
      audio.onended = () => URL.revokeObjectURL(url)
    } catch (err) {
      toast('播放失败: 文件不存在或无访问权限', 'error')
    }
  }
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
    await api.post(`/api/v1/security/components/${comp.component_id || comp.name}/enable`)
    comp.is_enabled = true; comp.enabled = true; toast('已启用')
  } catch (e) { toast('操作失败', 'error') }
}
async function disableComponent(comp) {
  try {
    await api.post(`/api/v1/security/components/${comp.component_id || comp.name}/disable`)
    comp.is_enabled = false; comp.enabled = false; toast('已禁用')
  } catch (e) { toast('操作失败', 'error') }
}
function openCompConfig(comp) {
  currentComp.value = comp
  compConfigJson.value = JSON.stringify(comp.config || {}, null, 2)
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
const currentCert = ref(null)
const allCerts = ref([])
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
  try {
    const r = await api.get('/api/v1/monitor/ssl/current')
    // Response shapes:
    //  Go backend: {certificates: [...], most_urgent: {...}}
    //  Python backend: [...] or single object
    const d = r.data
    if (Array.isArray(d)) {
      allCerts.value = d
      currentCert.value = d[0] || { exists: false }
    } else if (d && Array.isArray(d.certificates)) {
      allCerts.value = d.certificates
      currentCert.value = d.most_urgent || d.certificates[0] || { exists: false }
    } else {
      allCerts.value = d ? [d] : []
      currentCert.value = d || { exists: false }
    }
  } catch (e) {
    currentCert.value = { exists: false, error: e.response?.data?.detail || e.message }
    allCerts.value = []
  }
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
const versionPage = ref(1)
const versionPageSize = 10
const versionTotalPages = computed(() => Math.max(1, Math.ceil(versionHistory.value.length / versionPageSize)))
const pagedVersionHistory = computed(() => {
  const start = (versionPage.value - 1) * versionPageSize
  return versionHistory.value.slice(start, start + versionPageSize)
})
const pushRemark = ref('')
const pushing = ref(false)
const pushProgress = ref(0)
const pushStage = ref('')
const pushResult = ref(null)

async function loadSysInfo() {
  try { const r = await api.get('/api/v1/system/info'); sysInfo.value = r.data || {} } catch {}
}
async function refreshVersionHistory() {
  try { const r = await api.get('/api/v1/system/github/versions'); versionHistory.value = r.data || [] }
  catch { versionHistory.value = [] }
}
async function pushToGitHub() {
  pushing.value = true
  pushResult.value = null
  pushProgress.value = 10
  pushStage.value = '正在构建前端...'
  try {
    const progressTimer = setInterval(() => {
      if (pushProgress.value < 90) pushProgress.value += Math.random() * 8
    }, 1500)
    setTimeout(() => { pushStage.value = '正在提交代码...' }, 3000)
    setTimeout(() => { pushStage.value = '正在推送至 GitHub...' }, 8000)
    await api.post('/api/v1/system/github/push', { remark: pushRemark.value, branch: 'go', repo: 'https://github.com/joycar2010/hustle2026.git' })
    clearInterval(progressTimer)
    pushProgress.value = 100
    pushStage.value = '推送完成'
    pushResult.value = { ok: true, msg: '已成功推送至 GitHub go 分支' }
    pushRemark.value = ''
    await refreshVersionHistory()
  } catch (e) {
    pushResult.value = { ok: false, msg: '推送失败: ' + (e.response?.data?.detail || e.message) }
  } finally {
    pushing.value = false
    setTimeout(() => { pushResult.value = null }, 8000)
  }
}
async function rollback(hash) {
  if (!confirm(`确认回滚至版本 ${hash.substring(0,7)}？当前代码将被覆盖！`)) return
  const v = versionHistory.value.find(i => i.hash === hash)
  if (v) { v._rolling = true; v._loading = true }
  try {
    await api.post('/api/v1/system/github/rollback', { hash, branch: 'go' })
    toast('回滚成功，服务将自动重启')
    await refreshVersionHistory()
  } catch (e) { toast('回滚失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { if (v) { v._rolling = false; v._loading = false } }
}
async function deleteVersion(hash) {
  if (!confirm(`确认从 go 分支删除版本 ${hash.substring(0,7)}？`)) return
  const v = versionHistory.value.find(i => i.hash === hash)
  if (v) { v._deleting = true; v._loading = true }
  try {
    await api.delete(`/api/v1/system/github/backup/${hash}`)
    toast('版本已成功删除')
    await refreshVersionHistory()
  } catch (e) { toast('删除失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { if (v) { v._deleting = false; v._loading = false } }
}

// ════════════════════════════════════════════
// ⑧ 数据库管理
// ════════════════════════════════════════════
const dbStats = ref({ size: null, tables: null, connections: null })
const dbTables = ref([])
const showTableViewModal = ref(false)
const tableViewName = ref('')
const tableViewLoading = ref(false)
const tableViewColumns = ref([])
const tableViewRows = ref([])
const showRestoreModal = ref(false)
const restoreLoading = ref(false)
const backupFiles = ref([])

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
    await api.post('/api/v1/system/database/backup', { target: 'github', branch: 'go', repo: 'https://github.com/joycar2010/hustle2026.git' })
    toast('数据库备份已提交至 go 分支')
    await refreshVersionHistory()
  } catch (e) { toast('备份失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function restoreDatabase() {
  showRestoreModal.value = true
  restoreLoading.value = true
  backupFiles.value = []
  try {
    const r = await api.get('/api/v1/system/database/backups')
    backupFiles.value = Array.isArray(r.data) ? r.data : []
  } catch (e) { toast('加载备份列表失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { restoreLoading.value = false }
}
async function confirmRestore(filename) {
  if (!confirm(`确认从备份文件「${filename}」恢复数据库？当前数据将被覆盖！`)) return
  try {
    await api.post('/api/v1/system/database/restore', { filename })
    toast('数据库恢复成功')
    showRestoreModal.value = false
  } catch (e) { toast('恢复失败: ' + (e.response?.data?.detail || e.message), 'error') }
}
async function clearDbLogs() {
  if (!confirm('确认清空 go 服务器 PostgreSQL 日志表？此操作不可恢复！')) return
  try { await api.post('/api/v1/system/database/clean-logs'); toast('go 服务器日志表已清空') }
  catch (e) { toast('清空失败', 'error') }
}
async function viewTable(name) {
  showTableViewModal.value = true
  tableViewName.value = name
  tableViewLoading.value = true
  tableViewColumns.value = []
  tableViewRows.value = []
  try {
    const r = await api.get(`/api/v1/system/database/table/${name}`)
    tableViewColumns.value = r.data.columns || []
    tableViewRows.value = r.data.rows || []
  } catch (e) { toast('加载表数据失败: ' + (e.response?.data?.detail || e.message), 'error') }
  finally { tableViewLoading.value = false }
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
  if (tab === 'push') {
    loadPushStreamStats()  // Load real stats first
    connectPushWs()
    startPushTimers()
  } else {
    disconnectPushWs()
  }
})
</script>

<style scoped>
.card { @apply bg-dark-100 rounded-2xl border border-border-primary p-6; }
</style>
