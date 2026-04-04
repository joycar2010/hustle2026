<template>
  <div class="container mx-auto px-4 py-6 space-y-6">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-text-primary">总控面板</h1>
        <p class="text-sm text-text-tertiary mt-0.5">实时监控所有服务器与用户资金状态</p>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-xs text-text-tertiary">最后更新: {{ lastUpdate }}</span>
        <button @click="refreshAll" :disabled="refreshing" class="flex items-center gap-1.5 px-3 py-1.5 bg-dark-50 hover:bg-dark-100 rounded-lg text-sm transition-colors disabled:opacity-50">
          <svg :class="['w-4 h-4', refreshing && 'animate-spin']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          刷新
        </button>
      </div>
    </div>

    <!-- ===== 服务器状态卡片行 ===== -->
    <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">

      <!-- GO 服务器 -->
      <div class="bg-dark-100 rounded-xl p-4 border" :class="goStatus.online ? 'border-green-800/50' : 'border-red-800/50'">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div :class="['w-2.5 h-2.5 rounded-full', goStatus.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
            <span class="text-sm font-semibold text-text-primary">GO 服务器</span>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full" :class="goStatus.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
            {{ goStatus.online ? '在线' : '离线' }}
          </span>
        </div>
        <div class="text-xs text-text-tertiary space-y-1">
          <div class="flex justify-between"><span>运行时长</span><span class="text-text-secondary font-mono">{{ goStatus.uptime || '--' }}</span></div>
          <div class="flex justify-between"><span>内存(Redis)</span><span class="text-text-secondary font-mono">{{ goStatus.memory || '--' }}</span></div>
          <div class="flex justify-between"><span>Redis 连接</span>
            <span :class="goStatus.redis ? 'text-green-400' : 'text-red-400'">{{ goStatus.redis ? '正常' : '异常' }}</span>
          </div>
        </div>
      </div>

      <!-- MT5 服务器 -->
      <div class="bg-dark-100 rounded-xl p-4 border" :class="mt5Server.online ? 'border-green-800/50' : 'border-red-800/50'">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div :class="['w-2.5 h-2.5 rounded-full', mt5Server.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
            <span class="text-sm font-semibold text-text-primary">MT5 服务器</span>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full" :class="mt5Server.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
            {{ mt5Server.online ? '在线' : '离线' }}
          </span>
        </div>
        <div class="text-xs text-text-tertiary space-y-1">
          <div class="flex justify-between"><span>Agent 实例</span><span class="text-text-secondary font-mono">{{ mt5Server.runningInstances }}/{{ mt5Server.totalInstances }}</span></div>
          <div v-for="inst in agentInstances" :key="inst.instance_name" class="flex justify-between">
            <span class="truncate max-w-[55%]">{{ inst.instance_name }}</span>
            <span :class="inst.is_running ? 'text-green-400' : 'text-red-400'" class="font-mono">
              {{ inst.is_running ? 'CPU ' + (inst.health_status?.details?.cpu_percent?.toFixed(0) ?? '--') + '%' : '停止' }}
            </span>
          </div>
        </div>
      </div>

      <!-- MT5 系统账户 -->
      <div class="bg-dark-100 rounded-xl p-4 border" :class="mt5System.online ? 'border-green-800/50' : 'border-red-800/50'">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div :class="['w-2.5 h-2.5 rounded-full', mt5System.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
            <span class="text-sm font-semibold text-text-primary">MT5 系统账户</span>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full" :class="mt5System.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
            {{ mt5System.online ? '在线' : '离线' }}
          </span>
        </div>
        <div class="text-xs text-text-tertiary space-y-1">
          <div class="flex justify-between"><span>MT5 登录</span><span class="text-text-secondary font-mono">{{ mt5System.login || '--' }}</span></div>
          <div class="flex justify-between"><span>服务器</span><span class="text-text-secondary">{{ mt5System.server || '--' }}</span></div>
          <div class="flex justify-between"><span>连接状态</span>
            <span :class="mt5System.connected ? 'text-green-400' : 'text-yellow-400'">{{ mt5System.connected ? '已连接' : '未连接' }}</span>
          </div>
          <div v-if="mt5System.balance != null" class="flex justify-between"><span>余额</span><span class="text-text-secondary font-mono">{{ mt5System.balance?.toFixed(2) }}</span></div>
          <div v-if="mt5System.equity != null" class="flex justify-between"><span>净值</span><span class="text-text-secondary font-mono">{{ mt5System.equity?.toFixed(2) }}</span></div>
        </div>
      </div>

      <!-- Redis -->
      <div class="bg-dark-100 rounded-xl p-4 border" :class="monitorData.redis?.connected ? 'border-green-800/50' : 'border-red-800/50'">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div :class="['w-2.5 h-2.5 rounded-full', monitorData.redis?.connected ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
            <span class="text-sm font-semibold text-text-primary">Redis</span>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full" :class="monitorData.redis?.connected ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
            {{ monitorData.redis?.connected ? '已连接' : '未连接' }}
          </span>
        </div>
        <div class="text-xs text-text-tertiary space-y-1">
          <div class="flex justify-between"><span>版本</span><span class="text-text-secondary">{{ monitorData.redis?.version || '--' }}</span></div>
          <div class="flex justify-between"><span>内存</span><span class="text-text-secondary">{{ monitorData.redis?.used_memory_human || '--' }}</span></div>
          <div class="flex justify-between"><span>客户端数</span><span class="text-text-secondary">{{ monitorData.redis?.connected_clients || '--' }}</span></div>
        </div>
      </div>

      <!-- SSL & 飞书 -->
      <div class="bg-dark-100 rounded-xl p-4 border" :class="sslOverallOk ? 'border-green-800/50' : 'border-yellow-800/50'">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <div :class="['w-2.5 h-2.5 rounded-full', sslOverallOk ? 'bg-green-500 animate-pulse' : 'bg-yellow-500']"></div>
            <span class="text-sm font-semibold text-text-primary">SSL 证书</span>
          </div>
          <span class="text-xs px-2 py-0.5 rounded-full" :class="sslOverallOk ? 'bg-green-900/40 text-green-400' : 'bg-yellow-900/40 text-yellow-400'">
            {{ sslOverallOk ? '正常' : '警告' }}
          </span>
        </div>
        <div class="text-xs text-text-tertiary space-y-1">
          <div v-for="cert in (monitorData.ssl_certificate || [])" :key="cert.cert_path || cert.domain_names?.[0]" class="flex justify-between">
            <span class="truncate max-w-[55%]">{{ cert.domain_names?.[0]?.replace('.hustle2026.xyz','') || '--' }}</span>
            <span :class="sslDaysClass(cert.days_remaining)">{{ cert.exists ? cert.days_remaining + '天' : '缺失' }}</span>
          </div>
          <div class="flex justify-between pt-1 border-t border-border-secondary"><span>飞书通知</span>
            <span :class="monitorData.feishu?.status === 'healthy' ? 'text-green-400' : 'text-yellow-400'">
              {{ feishuText(monitorData.feishu?.status) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== MT5 客户端状态面板（完整版） ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary">
      <button
        @click="sysMonOpen = !sysMonOpen"
        class="w-full flex items-center justify-between px-5 py-4 border-b border-border-secondary hover:bg-dark-50 transition-colors"
      >
        <div class="flex items-center gap-2">
          <div :class="['w-2.5 h-2.5 rounded-full', mt5ClientsList.some(c => c.connection_status === 'connected') ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
          <h2 class="text-base font-semibold text-text-primary">MT5 客户端状态</h2>
          <span class="text-xs px-2 py-0.5 rounded-full bg-dark-200 text-text-secondary">
            {{ mt5ClientsList.filter(c => c.connection_status === 'connected').length }}/{{ mt5ClientsList.length }} 在线
          </span>
        </div>
        <svg :class="['w-4 h-4 text-text-tertiary transition-transform', sysMonOpen ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>

      <div v-if="sysMonOpen" class="p-5">
        <div v-if="mt5ClientsList.length" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <div v-for="c in mt5ClientsList" :key="c.client_id"
            class="bg-dark-200 rounded-xl p-4 border space-y-3"
            :class="c.connection_status === 'connected' ? 'border-green-800/30' : 'border-red-800/30'">

            <!-- 头部 -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <div :class="['w-2.5 h-2.5 rounded-full', c.connection_status === 'connected' ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
                <span class="font-semibold text-sm text-text-primary">{{ c.client_name }}</span>
              </div>
              <div class="flex items-center gap-1.5">
                <span v-if="c.is_system_service" class="px-1.5 py-0.5 rounded text-xs bg-[#f0b90b]/20 text-[#f0b90b]">系统服务</span>
                <span class="text-xs px-2 py-0.5 rounded-full" :class="c.connection_status === 'connected' ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
                  {{ c.connection_status === 'connected' ? '已连接' : '未连接' }}
                </span>
              </div>
            </div>

            <!-- 详情 -->
            <div class="text-xs space-y-1.5">
              <div class="flex justify-between"><span class="text-text-tertiary">用户</span><span class="text-text-secondary">{{ c.username }}</span></div>
              <div class="flex justify-between"><span class="text-text-tertiary">MT5 登录</span><span class="font-mono">{{ c.mt5_login }}</span></div>
              <div class="flex justify-between"><span class="text-text-tertiary">服务器</span><span class="font-mono">{{ c.mt5_server }}</span></div>
              <div class="flex justify-between"><span class="text-text-tertiary">密码类型</span><span>{{ c.password_type === 'primary' ? '主密码' : '只读密码' }}</span></div>
              <div class="flex justify-between"><span class="text-text-tertiary">代理</span>
                <span v-if="c._proxy_config && c._proxy_config.host" class="font-mono text-xs">
                  {{ c._proxy_config.host }}:{{ c._proxy_config.port }}
                  <span v-if="c._proxy_config.expires_at" class="ml-1" :class="mdProxyDaysLeft(c._proxy_config.expires_at) <= 7 ? 'text-red-400' : 'text-text-tertiary'">
                    ({{ c._proxy_config.expires_at }}<span v-if="mdProxyDaysLeft(c._proxy_config.expires_at) <= 7">, {{ mdProxyDaysLeft(c._proxy_config.expires_at) }}天</span>)
                  </span>
                </span>
                <span v-else class="text-text-tertiary">直连</span>
              </div>
              <div v-if="c.last_connected_at" class="flex justify-between"><span class="text-text-tertiary">最后心跳</span>
                <span class="text-text-secondary">{{ formatLastSeen(c.last_connected_at) }}</span>
              </div>
            </div>

            <!-- Bridge 服务 -->
            <div v-if="c.bridge_service_name" class="bg-dark-300 rounded-lg p-2.5 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs text-text-tertiary font-medium">Bridge 服务</span>
                <span class="px-1.5 py-0.5 rounded text-xs" :class="getBridgeStatusClass(c)">{{ getBridgeStatusText(c) }}</span>
              </div>
              <div class="text-xs space-y-1">
                <div class="flex justify-between"><span class="text-text-tertiary">服务名</span><span class="font-mono">{{ c.bridge_service_name }}</span></div>
                <div class="flex justify-between"><span class="text-text-tertiary">端口</span><span class="font-mono">{{ c.bridge_service_port }}</span></div>
              </div>
              <div class="flex gap-1.5">
                <button @click="bridgeControl(c, 'start')"
                  :disabled="bridgeStatus[c.client_id]?.is_running || bridgeLoading[c.client_id]"
                  class="flex-1 py-1 rounded text-xs border transition-colors"
                  :class="bridgeStatus[c.client_id]?.is_running || bridgeLoading[c.client_id] ? 'bg-dark-300 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] border-[#0ecb81]/20'">
                  {{ bridgeLoading[c.client_id] === 'start' ? '...' : '启动' }}
                </button>
                <button @click="bridgeControl(c, 'stop')"
                  :disabled="!bridgeStatus[c.client_id]?.is_running || bridgeLoading[c.client_id]"
                  class="flex-1 py-1 rounded text-xs border transition-colors"
                  :class="!bridgeStatus[c.client_id]?.is_running || bridgeLoading[c.client_id] ? 'bg-dark-300 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] border-[#f6465d]/20'">
                  {{ bridgeLoading[c.client_id] === 'stop' ? '...' : '停止' }}
                </button>
                <button @click="bridgeControl(c, 'restart')"
                  :disabled="!bridgeStatus[c.client_id]?.is_running || bridgeLoading[c.client_id]"
                  class="flex-1 py-1 rounded text-xs border transition-colors"
                  :class="!bridgeStatus[c.client_id]?.is_running || bridgeLoading[c.client_id] ? 'bg-dark-300 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] border-[#f0b90b]/20'">
                  {{ bridgeLoading[c.client_id] === 'restart' ? '...' : '重启' }}
                </button>
              </div>
            </div>

            <!-- 远程控制 -->
            <div v-if="c.agent_instance_name" class="bg-dark-300 rounded-lg p-2.5 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs text-text-tertiary font-medium">MT5 远程控制</span>
                <span class="px-1.5 py-0.5 rounded text-xs" :class="getAgentStatusClass(c)">{{ getAgentStatusText(c) }}</span>
              </div>
              <div v-if="agentStatus[c.agent_instance_name]?.is_running && agentStatus[c.agent_instance_name]?.health_status?.details?.cpu_percent !== undefined" class="text-xs space-y-1">
                <div class="flex justify-between"><span class="text-text-tertiary">CPU</span><span>{{ agentStatus[c.agent_instance_name]?.health_status?.details?.cpu_percent?.toFixed(1) }}%</span></div>
                <div class="flex justify-between"><span class="text-text-tertiary">内存</span><span>{{ agentStatus[c.agent_instance_name]?.health_status?.details?.memory_mb?.toFixed(0) }} MB</span></div>
              </div>
              <div class="flex gap-1.5">
                <button @click="agentControl(c, 'start')"
                  :disabled="agentStatus[c.agent_instance_name]?.is_running || agentLoading[c.agent_instance_name]"
                  class="flex-1 py-1 rounded text-xs border transition-colors"
                  :class="agentStatus[c.agent_instance_name]?.is_running || agentLoading[c.agent_instance_name] ? 'bg-dark-300 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#0ecb81]/10 hover:bg-[#0ecb81]/20 text-[#0ecb81] border-[#0ecb81]/20'">
                  {{ agentLoading[c.agent_instance_name] === 'start' ? '...' : '启动' }}
                </button>
                <button @click="agentControl(c, 'stop')"
                  :disabled="!agentStatus[c.agent_instance_name]?.is_running || agentLoading[c.agent_instance_name]"
                  class="flex-1 py-1 rounded text-xs border transition-colors"
                  :class="!agentStatus[c.agent_instance_name]?.is_running || agentLoading[c.agent_instance_name] ? 'bg-dark-300 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#f6465d]/10 hover:bg-[#f6465d]/20 text-[#f6465d] border-[#f6465d]/20'">
                  {{ agentLoading[c.agent_instance_name] === 'stop' ? '...' : '停止' }}
                </button>
                <button @click="agentControl(c, 'restart')"
                  :disabled="!agentStatus[c.agent_instance_name]?.is_running || agentLoading[c.agent_instance_name]"
                  class="flex-1 py-1 rounded text-xs border transition-colors"
                  :class="!agentStatus[c.agent_instance_name]?.is_running || agentLoading[c.agent_instance_name] ? 'bg-dark-300 text-text-tertiary border-border-primary cursor-not-allowed' : 'bg-[#f0b90b]/10 hover:bg-[#f0b90b]/20 text-[#f0b90b] border-[#f0b90b]/20'">
                  {{ agentLoading[c.agent_instance_name] === 'restart' ? '...' : '重启' }}
                </button>
              </div>
            </div>

          </div>
        </div>
        <div v-else class="text-center text-text-tertiary py-8">暂无 MT5 客户端数据</div>
        <div class="text-xs text-text-tertiary text-right mt-4 pt-4 border-t border-border-secondary">
          最后更新: {{ monitorData.timestamp ? new Date(monitorData.timestamp).toLocaleString('zh-CN') : '--' }}
        </div>
      </div>
    </div>

    <!-- ===== 性能监控面板 ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary">
      <button @click="perfMonOpen = !perfMonOpen"
        class="w-full flex items-center justify-between px-5 py-4 border-b border-border-secondary hover:bg-dark-50 transition-colors">
        <div class="flex items-center gap-2">
          <div class="w-2.5 h-2.5 rounded-full bg-primary animate-pulse"></div>
          <h2 class="text-base font-semibold text-text-primary">性能监控</h2>
        </div>
        <svg :class="['w-4 h-4 text-text-tertiary transition-transform', perfMonOpen ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>
      <div v-if="perfMonOpen" class="p-5 space-y-4">
        <div class="bg-dark-200 rounded-lg p-4">
          <div class="flex items-center justify-between mb-3">
            <span class="font-medium text-sm">Redis</span>
            <span :class="['text-xs', monitorData.redis?.connected ? 'text-green-400' : 'text-red-400']">{{ monitorData.redis?.connected ? '正常' : '异常' }}</span>
          </div>
          <div class="grid grid-cols-2 gap-4 text-xs">
            <div><div class="text-text-tertiary mb-1">内存使用</div><div class="text-text-primary text-lg font-mono">{{ monitorData.redis?.used_memory_human || '--' }}</div></div>
            <div><div class="text-text-tertiary mb-1">客户端连接数</div><div class="text-text-primary text-lg font-mono">{{ monitorData.redis?.connected_clients ?? '--' }}</div></div>
            <div><div class="text-text-tertiary mb-1">运行时间</div><div class="text-text-secondary font-mono">{{ goStatus.uptime || '--' }}</div></div>
            <div><div class="text-text-tertiary mb-1">版本</div><div class="text-text-secondary font-mono">{{ monitorData.redis?.version || '--' }}</div></div>
          </div>
        </div>
        <div class="bg-dark-200 rounded-lg p-4">
          <div class="flex items-center justify-between mb-3">
            <span class="font-medium text-sm">数据库 (PostgreSQL)</span>
            <span :class="['text-xs', perfData.database?.status === 'healthy' ? 'text-green-400' : 'text-yellow-400']">{{ perfData.database?.status === 'healthy' ? '正常' : (perfData.database?.status || '检测中') }}</span>
          </div>
          <div class="text-xs"><div class="text-text-tertiary mb-1">查询延迟</div><div class="text-text-primary text-lg font-mono">{{ perfData.database?.latency_ms?.toFixed(2) ?? '--' }} ms</div></div>
        </div>
        <div class="bg-dark-200 rounded-lg p-4">
          <div class="flex items-center justify-between mb-3">
            <span class="font-medium text-sm">MT5 桥接服务</span>
            <span :class="['text-xs', mt5Server.online ? 'text-green-400' : 'text-red-400']">{{ mt5Server.online ? '在线' : '离线' }}</span>
          </div>
          <div class="grid grid-cols-2 gap-4 text-xs">
            <div><div class="text-text-tertiary mb-1">运行实例</div><div class="text-text-primary text-lg font-mono">{{ mt5Server.runningInstances }}/{{ mt5Server.totalInstances }}</div></div>
            <div><div class="text-text-tertiary mb-1">系统账户</div><div :class="mt5System.connected ? 'text-green-400' : 'text-red-400'">{{ mt5System.connected ? '已连接' : '未连接' }}</div></div>
          </div>
        </div>
        <div class="text-xs text-text-tertiary text-right">{{ monitorData.timestamp ? new Date(monitorData.timestamp).toLocaleString('zh-CN') : '--' }}</div>
      </div>
    </div>

    <!-- ===== 用户资金汇总表 ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary">
      <div class="flex items-center justify-between px-5 py-4 border-b border-border-secondary">
        <h2 class="text-base font-semibold text-text-primary">所有用户实时资金状态</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs text-text-tertiary">10s 自动刷新</span>
          <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border-secondary text-text-tertiary text-xs">
              <th class="text-left px-5 py-3">用户名</th><th class="text-left px-4 py-3">角色</th>
              <th class="text-right px-4 py-3">账户数</th><th class="text-right px-4 py-3">总资产 (USDT)</th>
              <th class="text-right px-4 py-3">可用资产</th><th class="text-right px-4 py-3">净资产</th>
              <th class="text-right px-4 py-3">当日盈亏</th><th class="text-right px-5 py-3">风险率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="usersLoading"><td colspan="8" class="text-center py-12 text-text-tertiary">加载中...</td></tr>
            <tr v-else-if="!userFinancials.length"><td colspan="8" class="text-center py-12 text-text-tertiary">暂无数据</td></tr>
            <tr v-for="u in userFinancials" :key="u.user_id" class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
              <td class="px-5 py-3 font-medium text-text-primary">{{ u.username }}</td>
              <td class="px-4 py-3"><span class="px-2 py-0.5 rounded text-xs" :class="roleBadgeClass(u.role)">{{ u.role || '--' }}</span></td>
              <td class="px-4 py-3 text-right text-text-secondary">{{ u.account_count ?? '--' }}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold">{{ fmtNum(u.total_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(u.available_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(u.net_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold" :class="pnlClass(u.daily_pnl)">
                {{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}
              </td>
              <td class="px-5 py-3 text-right"><span :class="riskClass(u.risk_rate)">{{ u.risk_rate != null ? u.risk_rate.toFixed(2) + '%' : '--' }}</span></td>
            </tr>
          </tbody>
          <tfoot v-if="userFinancials.length" class="border-t-2 border-border-primary">
            <tr class="bg-dark-50 text-sm font-semibold">
              <td class="px-5 py-3 text-text-secondary" colspan="3">合计</td>
              <td class="px-4 py-3 text-right font-mono">{{ fmtNum(totals.total_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(totals.available_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(totals.net_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono" :class="pnlClass(totals.daily_pnl)">{{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}</td>
              <td class="px-5 py-3"></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/services/api.js'
import dayjs from 'dayjs'

// --- State ---
const refreshing = ref(false)
const usersLoading = ref(true)
const lastUpdate = ref('--')
const sysMonOpen = ref(false)
const perfMonOpen = ref(false)

const goStatus = ref({ online: false, uptime: '', memory: '', redis: false })
const mt5System = ref({ online: false, login: '', server: '', connected: false, balance: null, equity: null })
const mt5Server = ref({ online: false, totalInstances: 0, runningInstances: 0 })
const agentInstances = ref([])
const userFinancials = ref([])
const monitorData = ref({ redis: null, ssl_certificate: [], feishu: null, mt5_clients: [] })
const perfData = ref({ database: {}, timestamp: null })
const mt5ClientsList = ref([])

// Bridge & Agent control state
const bridgeStatus = ref({})
const bridgeLoading = ref({})
const agentStatus = ref({})
const agentLoading = ref({})

let timer = null

// --- Computed ---
const totals = computed(() => ({
  total_assets:     userFinancials.value.reduce((s, u) => s + (u.total_assets || 0), 0),
  available_assets: userFinancials.value.reduce((s, u) => s + (u.available_assets || 0), 0),
  net_assets:       userFinancials.value.reduce((s, u) => s + (u.net_assets || 0), 0),
  daily_pnl:        userFinancials.value.reduce((s, u) => s + (u.daily_pnl || 0), 0),
}))
const sslOverallOk = computed(() =>
  (monitorData.value.ssl_certificate || []).every(c => c.status !== 'expired' && c.status !== 'critical' && c.status !== 'error')
)

// --- Data Fetching ---
async function fetchMonitorStatus() {
  try {
    const r = await api.get('/api/v1/monitor/status')
    const d = r.data
    monitorData.value = d

    // GO server card: derive from Redis
    const uptimeSec = parseInt(d.redis?.uptime_seconds || '0')
    const h = Math.floor(uptimeSec / 3600), m = Math.floor((uptimeSec % 3600) / 60)
    goStatus.value = {
      online: true,
      uptime: uptimeSec > 86400 ? `${Math.floor(uptimeSec / 86400)}天${h % 24}时` : `${h}时${m}分`,
      memory: d.redis?.used_memory_human || '--',
      redis: d.redis?.connected ?? false,
    }

    // Build enriched MT5 clients list from monitor data
    // Monitor provides: client_id, client_name, mt5_login, mt5_server, connection_status, online, process_running, last_connected_at, username
    // We need to enrich with DB fields: bridge_service_name, bridge_service_port, agent_instance_name, password_type, proxy_id, is_system_service
    await enrichMT5Clients(d.mt5_clients || [])
  } catch {
    goStatus.value.online = false
  }
}

async function enrichMT5Clients(monitorClients) {
  // Try to get full client details from DB via any user's account
  try {
    // Get all accounts to find account_ids with MT5 clients
    const accsRes = await api.get('/api/v1/accounts/')
    const accounts = Array.isArray(accsRes.data) ? accsRes.data : []

    // For each account, get its MT5 clients
    const allDbClients = []
    for (const acc of accounts) {
      try {
        const r = await api.get(`/api/v1/accounts/${acc.account_id}/mt5-clients`)
        const clients = Array.isArray(r.data) ? r.data : r.data?.clients || []
        clients.forEach(c => { c._username = acc.account_name || acc.user_id })
        allDbClients.push(...clients)
      } catch {}
    }

    // Merge monitor data with DB data
    const dbMap = {}
    allDbClients.forEach(c => { dbMap[String(c.client_id)] = c })
    const accMap = {}
    accounts.forEach(a => { accMap[String(a.account_id)] = a })

    mt5ClientsList.value = monitorClients.map(mc => {
      const db = dbMap[String(mc.client_id)] || {}
      const linkedAcc = accMap[String(db.account_id)] || null
      return {
        ...mc,
        bridge_service_name: db.bridge_service_name || null,
        bridge_service_port: db.bridge_service_port || null,
        agent_instance_name: db.agent_instance_name || null,
        password_type: db.password_type || 'primary',
        proxy_id: db.proxy_id || null,
        _proxy_config: linkedAcc?.proxy_config || null,
        is_system_service: db.is_system_service || false,
        is_active: db.is_active ?? true,
      }
    })
  } catch {
    // Fallback: use monitor data as-is
    mt5ClientsList.value = monitorClients
  }
}

async function fetchMT5Status() {
  // System MT5 account
  try {
    const r = await api.get('/api/v1/mt5-clients/system-service/status')
    mt5System.value = {
      online: r.data.connected,
      login: r.data.mt5_login || '--',
      server: r.data.mt5_server || '--',
      connected: r.data.connected,
      balance: r.data.balance,
      equity: r.data.equity,
    }
  } catch {
    mt5System.value = { online: false, login: '--', server: '--', connected: false, balance: null, equity: null }
  }

  // MT5 Agent instances → MT5 Server card
  try {
    const r = await api.get('/api/v1/mt5-agent/instances')
    const instances = Array.isArray(r.data) ? r.data : []
    agentInstances.value = instances
    const running = instances.filter(i => i.is_running).length
    mt5Server.value = { online: running > 0, totalInstances: instances.length, runningInstances: running }

    // Build agentStatus map
    const statusMap = {}
    instances.forEach(inst => { statusMap[inst.instance_name] = inst })
    agentStatus.value = statusMap
  } catch {
    mt5Server.value = { online: false, totalInstances: 0, runningInstances: 0 }
    agentInstances.value = []
  }
}

async function loadBridgeStatus() {
  for (const c of mt5ClientsList.value) {
    if (c.bridge_service_name) {
      try {
        const r = await api.get(`/api/v1/mt5-agent/bridge/${c.client_id}/status`)
        bridgeStatus.value[c.client_id] = r.data
      } catch {}
    }
  }
}

async function fetchPerformance() {
  try {
    const t0 = performance.now()
    await api.get('/api/v1/system/info')
    perfData.value.database = { status: 'healthy', latency_ms: performance.now() - t0 }
  } catch {
    perfData.value.database = { status: 'error', latency_ms: null }
  }
  perfData.value.timestamp = new Date().toISOString()
}

function mdProxyDaysLeft(dateStr) {
  if (!dateStr) return 999
  const exp = new Date(dateStr + 'T00:00:00')
  const now = new Date()
  now.setHours(0,0,0,0)
  return Math.floor((exp - now) / 86400000)
}

async function fetchUserFinancials() {
  usersLoading.value = true
  try {
    const r = await api.get('/api/v1/accounts/dashboard/admin-summary')
    userFinancials.value = (r.data?.users || []).map(u => ({
      ...u,
      role: u.role || '--',
    }))
  } catch (e) {
    console.error('fetchUserFinancials error:', e)
    userFinancials.value = []
  } finally { usersLoading.value = false }
}

// --- Bridge & Agent Control ---
async function bridgeControl(client, action) {
  if (!client.bridge_service_name) return
  const txt = { start: '启动', stop: '停止', restart: '重启' }[action]
  if (!confirm(`确定要${txt} ${client.client_name} 的 Bridge 服务吗？`)) return
  try {
    bridgeLoading.value[client.client_id] = action
    const r = await api.post(`/api/v1/mt5-agent/bridge/${client.client_id}/${action}`)
    if (r.data.success) {
      setTimeout(loadBridgeStatus, action === 'stop' ? 1000 : 3000)
    } else { alert(`${txt}失败: ${r.data.message}`) }
  } catch (e) { alert(`${txt}失败: ${e.response?.data?.detail || e.message}`) }
  finally { bridgeLoading.value[client.client_id] = null }
}

async function agentControl(client, action) {
  if (!client.agent_instance_name) return
  const txt = { start: '启动', stop: '停止', restart: '重启' }[action]
  if (!confirm(`确定要${txt} ${client.client_name} 吗？`)) return
  try {
    agentLoading.value[client.agent_instance_name] = action
    const r = await api.post(`/api/v1/mt5-agent/clients/${client.client_id}/${action}`,
      null, { params: action === 'stop' ? { force: true } : { wait_seconds: 5 } })
    if (r.data.success) {
      setTimeout(async () => { await fetchMT5Status() }, action === 'stop' ? 1000 : 3000)
    } else { alert(`${txt}失败: ${r.data.message}`) }
  } catch (e) { alert(`${txt}失败: ${e.response?.data?.detail || e.message}`) }
  finally { agentLoading.value[client.agent_instance_name] = null }
}

// --- Status Helpers ---
function getBridgeStatusClass(c) {
  if (!c.bridge_service_name) return 'bg-dark-200 text-text-tertiary'
  const s = bridgeStatus.value[c.client_id]
  return s?.is_running ? 'bg-[#0ecb81]/20 text-[#0ecb81]' : 'bg-dark-200 text-text-tertiary'
}
function getBridgeStatusText(c) {
  if (!c.bridge_service_name) return '未部署'
  const s = bridgeStatus.value[c.client_id]
  return s ? (s.is_running ? '运行中' : '已停止') : '未知'
}
function getAgentStatusClass(c) {
  if (!c.agent_instance_name) return 'bg-dark-200 text-text-tertiary'
  const s = agentStatus.value[c.agent_instance_name]
  if (!s?.is_running) return 'bg-dark-200 text-text-tertiary'
  if (s.health_status?.is_frozen || s.health_status?.cpu_high) return 'bg-[#f6465d]/20 text-[#f6465d]'
  return 'bg-[#0ecb81]/20 text-[#0ecb81]'
}
function getAgentStatusText(c) {
  if (!c.agent_instance_name) return '未配置'
  const s = agentStatus.value[c.agent_instance_name]
  return s ? (s.is_running ? '运行中' : '已停止') : '未知'
}

// --- Refresh ---
async function refreshAll() {
  refreshing.value = true
  await Promise.all([fetchMonitorStatus(), fetchMT5Status(), fetchUserFinancials(), fetchPerformance()])
  await loadBridgeStatus()
  lastUpdate.value = dayjs().format('HH:mm:ss')
  refreshing.value = false
}

// --- Helpers ---
function fmtNum(v) { return v == null ? '--' : parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function pnlClass(v) { return v == null ? '' : v >= 0 ? 'text-success' : 'text-danger' }
function riskClass(v) { return v == null ? 'text-text-tertiary' : v < 50 ? 'text-success' : v < 80 ? 'text-warning' : 'text-danger font-bold' }
function roleBadgeClass(role) { return { '管理员': 'bg-red-900/40 text-red-300', '交易员': 'bg-blue-900/40 text-blue-300', '观察员': 'bg-gray-700 text-gray-300' }[role] || 'bg-dark-200 text-text-secondary' }
function sslDaysClass(days) { return days == null ? 'text-text-tertiary' : days <= 7 ? 'text-red-400 font-bold' : days <= 30 ? 'text-yellow-400 font-bold' : 'text-green-400' }
function feishuText(s) { return { healthy: '正常', disabled: '已禁用', not_configured: '未配置' }[s] || s || '--' }
function formatLastSeen(ts) {
  if (!ts) return '--'
  const d = Math.floor((Date.now() - new Date(ts)) / 1000)
  return d < 60 ? `${d}秒前` : d < 3600 ? `${Math.floor(d / 60)}分钟前` : d < 86400 ? `${Math.floor(d / 3600)}小时前` : `${Math.floor(d / 86400)}天前`
}

onMounted(() => { refreshAll(); timer = setInterval(refreshAll, 10000) })
onUnmounted(() => { clearInterval(timer) })
</script>
