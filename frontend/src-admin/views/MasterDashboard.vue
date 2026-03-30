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
          <div class="flex justify-between"><span>Python Worker</span><span class="text-text-secondary">{{ goStatus.workers || '--' }}</span></div>
          <div class="flex justify-between"><span>内存使用</span><span class="text-text-secondary font-mono">{{ goStatus.memory || '--' }}</span></div>
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
          <div class="flex justify-between"><span>运行时长</span><span class="text-text-secondary font-mono">{{ mt5Server.uptime || '--' }}</span></div>
          <div class="flex justify-between"><span>内存使用</span><span class="text-text-secondary font-mono">{{ mt5Server.memory || '--' }}</span></div>
          <div class="flex justify-between"><span>CPU 使用</span><span class="text-text-secondary font-mono">{{ mt5Server.cpu || '--' }}</span></div>
          <div class="flex justify-between"><span>运行实例</span><span class="text-text-secondary">{{ mt5Server.instances ?? '--' }}</span></div>
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
          <div class="flex justify-between"><span>端口</span><span class="text-text-secondary font-mono">:8001</span></div>
          <div class="flex justify-between"><span>MT5 登录</span><span class="text-text-secondary font-mono">{{ mt5System.login || '--' }}</span></div>
          <div class="flex justify-between"><span>连接状态</span>
            <span :class="mt5System.connected ? 'text-green-400' : 'text-yellow-400'">{{ mt5System.connected ? '已连接' : '未连接' }}</span>
          </div>
          <div class="flex justify-between"><span>服务器</span><span class="text-text-secondary">{{ mt5System.server || '--' }}</span></div>
          <div v-if="mt5System.balance != null" class="flex justify-between"><span>余额</span><span class="text-text-secondary font-mono">{{ mt5System.balance?.toFixed(2) }} UST</span></div>
        </div>
      </div>

      <!-- Redis & WebSocket -->
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
          <div class="flex justify-between"><span>WebSocket</span>
            <span class="text-green-400">正常</span>
          </div>
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
          <div v-if="monitorData.ssl_certificate?.length" class="space-y-0.5">
            <div v-for="cert in monitorData.ssl_certificate.slice(0, 2)" :key="cert.cert_path" class="flex justify-between">
              <span class="truncate max-w-[60%]">{{ cert.domain_names?.[0]?.split('.')[0] || '--' }}</span>
              <span :class="sslDaysClass(cert.days_remaining)">{{ cert.exists ? cert.days_remaining + '天' : '--' }}</span>
            </div>
          </div>
          <div class="flex justify-between pt-1 border-t border-border-secondary"><span>飞书通知</span>
            <span :class="monitorData.feishu?.status === 'healthy' ? 'text-green-400' : 'text-yellow-400'">
              {{ feishuText(monitorData.feishu?.status) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== MT5 客户端状态面板 ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary">
      <button
        @click="sysMonOpen = !sysMonOpen"
        class="w-full flex items-center justify-between px-5 py-4 border-b border-border-secondary hover:bg-dark-50 transition-colors"
      >
        <div class="flex items-center gap-2">
          <div :class="['w-2.5 h-2.5 rounded-full', monitorData.mt5_clients?.some(c => c.online) ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
          <h2 class="text-base font-semibold text-text-primary">MT5 客户端状态</h2>
          <span class="text-xs px-2 py-0.5 rounded-full bg-dark-200 text-text-secondary">
            {{ monitorData.mt5_clients?.filter(c=>c.online).length ?? 0 }}/{{ monitorData.mt5_clients?.length ?? 0 }} 在线
          </span>
        </div>
        <svg :class="['w-4 h-4 text-text-tertiary transition-transform', sysMonOpen ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>

      <div v-if="sysMonOpen" class="p-5">
        <div v-if="monitorData.mt5_clients?.length" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          <div v-for="c in monitorData.mt5_clients" :key="c.mt5_login"
            class="bg-dark-200 rounded-lg p-4 border" :class="c.online ? 'border-green-800/30' : 'border-red-800/30'">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <div :class="['w-2.5 h-2.5 rounded-full', c.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
                <span class="font-medium text-sm text-text-primary">{{ c.client_name }}</span>
              </div>
              <span class="text-xs px-2 py-0.5 rounded-full" :class="c.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
                {{ c.online ? '在线' : '离线' }}
              </span>
            </div>
            <div class="text-xs text-text-tertiary space-y-1">
              <div class="flex justify-between"><span>用户</span><span class="text-text-secondary">{{ c.username }}</span></div>
              <div class="flex justify-between"><span>MT5 登录</span><span class="text-text-secondary font-mono">{{ c.mt5_login }}</span></div>
              <div class="flex justify-between"><span>服务器</span><span class="text-text-secondary">{{ c.mt5_server || '--' }}</span></div>
              <div v-if="c.connection_status" class="flex justify-between"><span>连接状态</span>
                <span :class="c.connection_status === 'connected' ? 'text-green-400' : 'text-yellow-400'">
                  {{ c.connection_status === 'connected' ? '已连接' : '未连接' }}
                </span>
              </div>
              <div class="flex justify-between"><span>进程状态</span>
                <span :class="c.process_running ? 'text-green-400' : 'text-red-400'">
                  {{ c.process_running ? '运行中' : '已停止' }}
                </span>
              </div>
              <div v-if="c.last_connected_at" class="flex justify-between"><span>最后心跳</span>
                <span class="text-text-secondary">{{ formatLastSeen(c.last_connected_at) }}</span>
              </div>
            </div>

            <!-- 快速控制按钮 -->
            <div class="flex gap-1.5 mt-2 pt-2 border-t border-border-secondary">
              <button @click="restartMT5Instance(c)"
                class="flex-1 py-1 bg-[#3dccc7]/10 hover:bg-[#3dccc7]/20 text-[#3dccc7] rounded text-xs border border-[#3dccc7]/20 transition-colors">
                重启
              </button>
              <button @click="viewMT5Details(c)"
                class="flex-1 py-1 bg-primary/10 hover:bg-primary/20 text-primary rounded text-xs border border-primary/20 transition-colors">
                详情
              </button>
            </div>
          </div>
        </div>
        <div v-else class="text-center text-text-tertiary py-8">
          <svg class="w-12 h-12 mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <p>暂无 MT5 客户端数据</p>
        </div>
        <div class="text-xs text-text-tertiary text-right mt-4 pt-4 border-t border-border-secondary">
          最后更新: {{ monitorData.timestamp ? new Date(monitorData.timestamp).toLocaleString('zh-CN') : '--' }}
        </div>
      </div>
    </div>

    <!-- ===== 性能监控面板 ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary">
      <button
        @click="perfMonOpen = !perfMonOpen"
        class="w-full flex items-center justify-between px-5 py-4 border-b border-border-secondary hover:bg-dark-50 transition-colors"
      >
        <div class="flex items-center gap-2">
          <div class="w-2.5 h-2.5 rounded-full bg-primary animate-pulse"></div>
          <h2 class="text-base font-semibold text-text-primary">性能监控</h2>
        </div>
        <svg :class="['w-4 h-4 text-text-tertiary transition-transform', perfMonOpen ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>

      <div v-if="perfMonOpen" class="p-5 space-y-4">
        <!-- 系统资源 -->
        <div class="bg-dark-200 rounded-lg p-4">
          <div class="flex items-center gap-2 mb-3">
            <span class="font-medium text-sm">系统资源</span>
          </div>
          <div class="grid grid-cols-2 gap-4 text-xs">
            <div>
              <div class="text-text-tertiary mb-1">CPU 使用率</div>
              <div class="text-text-primary text-lg font-mono">{{ perfData.system?.cpu_percent?.toFixed(1) ?? '--' }}%</div>
            </div>
            <div>
              <div class="text-text-tertiary mb-1">内存使用率</div>
              <div class="text-text-primary text-lg font-mono">{{ perfData.system?.memory_percent?.toFixed(1) ?? '--' }}%</div>
            </div>
            <div>
              <div class="text-text-tertiary mb-1">可用内存</div>
              <div class="text-text-secondary font-mono">{{ perfData.system?.memory_available_mb?.toFixed(0) ?? '--' }} MB</div>
            </div>
            <div>
              <div class="text-text-tertiary mb-1">磁盘使用率</div>
              <div class="text-text-secondary font-mono">{{ perfData.system?.disk_percent?.toFixed(1) ?? '--' }}%</div>
            </div>
          </div>
        </div>

        <!-- 数据库性能 -->
        <div class="bg-dark-200 rounded-lg p-4">
          <div class="flex items-center justify-between mb-3">
            <span class="font-medium text-sm">数据库</span>
            <span :class="['text-xs', perfData.database?.status === 'healthy' ? 'text-green-400' : 'text-red-400']">
              {{ perfData.database?.status === 'healthy' ? '正常' : '异常' }}
            </span>
          </div>
          <div class="text-xs">
            <div class="text-text-tertiary mb-1">查询延迟</div>
            <div class="text-text-primary text-lg font-mono">{{ perfData.database?.latency_ms?.toFixed(2) ?? '--' }} ms</div>
          </div>
        </div>

        <!-- MT5 桥接性能 -->
        <div class="bg-dark-200 rounded-lg p-4">
          <div class="flex items-center justify-between mb-3">
            <span class="font-medium text-sm">MT5 桥接服务</span>
            <span :class="['text-xs', perfData.mt5_bridge?.status === 'healthy' ? 'text-green-400' : 'text-red-400']">
              {{ perfData.mt5_bridge?.status === 'healthy' ? '正常' : '异常' }}
            </span>
          </div>
          <div class="grid grid-cols-2 gap-4 text-xs">
            <div>
              <div class="text-text-tertiary mb-1">服务延迟</div>
              <div class="text-text-primary text-lg font-mono">{{ perfData.mt5_bridge?.latency_ms?.toFixed(2) ?? '--' }} ms</div>
            </div>
            <div v-if="perfData.mt5_bridge?.connection_pool">
              <div class="text-text-tertiary mb-1">连接池</div>
              <div class="text-text-secondary">
                活跃: {{ perfData.mt5_bridge.connection_pool.active ?? 0 }} /
                空闲: {{ perfData.mt5_bridge.connection_pool.idle ?? 0 }}
              </div>
            </div>
          </div>
        </div>

        <div class="text-xs text-text-tertiary text-right">{{ perfData.timestamp ? new Date(perfData.timestamp).toLocaleString('zh-CN') : '--' }}</div>
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
              <th class="text-left px-5 py-3 whitespace-nowrap">用户名</th>
              <th class="text-left px-4 py-3 whitespace-nowrap">角色</th>
              <th class="text-right px-4 py-3 whitespace-nowrap">账户数</th>
              <th class="text-right px-4 py-3 whitespace-nowrap">总资产 (USDT)</th>
              <th class="text-right px-4 py-3 whitespace-nowrap">可用资产</th>
              <th class="text-right px-4 py-3 whitespace-nowrap">净资产</th>
              <th class="text-right px-4 py-3 whitespace-nowrap">当日盈亏</th>
              <th class="text-right px-5 py-3 whitespace-nowrap">风险率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="usersLoading">
              <td colspan="8" class="text-center py-12 text-text-tertiary">
                <svg class="w-6 h-6 animate-spin mx-auto mb-2" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                加载中...
              </td>
            </tr>
            <tr v-else-if="!userFinancials.length">
              <td colspan="8" class="text-center py-12 text-text-tertiary">暂无数据</td>
            </tr>
            <tr
              v-for="u in userFinancials" :key="u.user_id"
              class="border-b border-border-secondary hover:bg-dark-50 transition-colors"
            >
              <td class="px-5 py-3 font-medium text-text-primary">{{ u.username }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs" :class="roleBadgeClass(u.role)">{{ u.role || '--' }}</span>
              </td>
              <td class="px-4 py-3 text-right text-text-secondary">{{ u.account_count ?? '--' }}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold">{{ fmtNum(u.total_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(u.available_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(u.net_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold" :class="pnlClass(u.daily_pnl)">
                {{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}
              </td>
              <td class="px-5 py-3 text-right">
                <span :class="riskClass(u.risk_rate)">{{ u.risk_rate != null ? u.risk_rate.toFixed(2) + '%' : '--' }}</span>
              </td>
            </tr>
          </tbody>
          <!-- 合计行 -->
          <tfoot v-if="userFinancials.length" class="border-t-2 border-border-primary">
            <tr class="bg-dark-50 text-sm font-semibold">
              <td class="px-5 py-3 text-text-secondary" colspan="3">合计</td>
              <td class="px-4 py-3 text-right font-mono">{{ fmtNum(totals.total_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(totals.available_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary">{{ fmtNum(totals.net_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono" :class="pnlClass(totals.daily_pnl)">
                {{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}
              </td>
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

const goStatus = ref({ online: false, uptime: '', workers: '', memory: '', redis: false })
const mt5System = ref({ online: false, login: '', server: '', connected: false })
const mt5Server = ref({ online: false, uptime: '', memory: '', cpu: '', instances: 0 })
const stats     = ref({ wsConnections: 0, totalUsers: 0, activeAccounts: 0, totalPositions: 0 })
const userFinancials = ref([])
const monitorData = ref({ redis: null, ssl_certificate: [], feishu: null, mt5_clients: [] })
const perfData = ref({ system: {}, database: {}, mt5_bridge: {}, timestamp: null })

let timer = null
let mt5Timer = null  // MT5 客户端状态专用定时器

// --- Computed ---
const totals = computed(() => ({
  total_assets:     userFinancials.value.reduce((s, u) => s + (u.total_assets || 0), 0),
  available_assets: userFinancials.value.reduce((s, u) => s + (u.available_assets || 0), 0),
  net_assets:       userFinancials.value.reduce((s, u) => s + (u.net_assets || 0), 0),
  daily_pnl:        userFinancials.value.reduce((s, u) => s + (u.daily_pnl || 0), 0),
}))
const sysMonHealthy = computed(() =>
  (monitorData.value.redis?.connected ?? false) &&
  (monitorData.value.ssl_certificate || []).every(c => c.status === 'healthy' || c.status === 'warning')
)
const sslOverallOk = computed(() =>
  (monitorData.value.ssl_certificate || []).every(c => c.status !== 'expired' && c.status !== 'critical')
)

// --- Methods ---
async function fetchMonitorStatus() {
  try {
    const r = await api.get('/api/v1/monitor/status')
    const d = r.data
    monitorData.value = d

    // GO server card: derive from Redis uptime and connected state
    const uptimeSec = parseInt(d.redis?.uptime_seconds || '0')
    const h = Math.floor(uptimeSec / 3600)
    const m = Math.floor((uptimeSec % 3600) / 60)
    const uptimeStr = uptimeSec > 86400
      ? `${Math.floor(uptimeSec / 86400)}天${Math.floor(h % 24)}时`
      : `${h}时${m}分`
    goStatus.value = {
      online: true,
      uptime: uptimeStr,
      workers: '--',
      memory: d.redis?.used_memory_human || '--',
      redis: d.redis?.connected ?? false,
    }

    // MT5 status cards — handled separately by fetchMT5Status()
    // (mt5_clients table may not exist in DB; we probe the microservice directly instead)
  } catch {
    goStatus.value.online = false
  }
}

async function fetchMT5Status() {
  // System MT5 account: 从系统服务账户获取状态
  try {
    const response = await api.get('/api/v1/mt5-clients/system-service/status')
    mt5System.value = {
      online: response.data.connected,
      login: response.data.mt5_login || '--',
      server: response.data.mt5_server || '--',
      connected: response.data.connected,
      balance: response.data.balance,
      equity: response.data.equity,
    }
  } catch (e) {
    console.error('Failed to fetch MT5 system status:', e)
    mt5System.value = {
      online: false,
      login: '--',
      server: '--',
      connected: false,
      balance: null,
      equity: null,
    }
  }

  // MT5 Server status via Windows Agent
  try {
    const r = await api.get('/api/v1/mt5-server/status')
    mt5Server.value = r.data
  } catch {
    mt5Server.value = { online: false, uptime: '--', memory: '--', cpu: '--', instances: 0 }
  }
}

async function fetchStats() {
  try {
    const r = await api.get('/api/v1/system/redis/status')
    stats.value.wsConnections = r.data?.ws_connections ?? 0
  } catch {}
}

async function fetchUserFinancials() {
  usersLoading.value = true
  try {
    // 获取所有用户列表
    const usersRes = await api.get('/api/v1/users')
    const users = Array.isArray(usersRes.data) ? usersRes.data : usersRes.data?.users || []
    stats.value.totalUsers = users.length

    // 为每个用户获取资金汇总
    const results = await Promise.allSettled(
      users.map(u => api.get('/api/v1/accounts/dashboard/aggregated').then(r => ({
        user_id: u.user_id || u.id,
        username: u.username,
        role: u.roles?.[0]?.role_name || u.role || '--',
        ...r.data,
      })))
    )

    let total_accounts = 0
    userFinancials.value = results
      .filter(r => r.status === 'fulfilled')
      .map(r => {
        total_accounts += r.value.account_count || 0
        return r.value
      })
    stats.value.activeAccounts = total_accounts
  } catch (e) {
    console.error('fetchUserFinancials error:', e)
  } finally {
    usersLoading.value = false
  }
}

async function fetchPerformance() {
  try {
    const r = await api.get('/api/v1/performance/system')
    perfData.value = r.data
  } catch (e) {
    console.error('fetchPerformance error:', e)
  }
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([fetchMonitorStatus(), fetchStats(), fetchUserFinancials(), fetchMT5Status(), fetchPerformance()])
  lastUpdate.value = dayjs().format('HH:mm:ss')
  refreshing.value = false
}

// --- Helpers ---
function fmtNum(v) {
  if (v == null) return '--'
  return parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function pnlClass(v) { return v == null ? '' : v >= 0 ? 'text-success' : 'text-danger' }
function riskClass(v) {
  if (v == null) return 'text-text-tertiary'
  if (v < 50) return 'text-success'
  if (v < 80) return 'text-warning'
  return 'text-danger font-bold'
}
function roleBadgeClass(role) {
  const m = { '超级管理员': 'bg-red-900/40 text-red-300', '系统管理员': 'bg-orange-900/40 text-orange-300', '安全管理员': 'bg-yellow-900/40 text-yellow-300', '交易员': 'bg-blue-900/40 text-blue-300', '观察员': 'bg-gray-700 text-gray-300' }
  return m[role] || 'bg-dark-200 text-text-secondary'
}
function sslDaysClass(days) {
  if (days == null) return 'text-text-tertiary'
  if (days <= 7) return 'text-red-400 font-bold'
  if (days <= 30) return 'text-yellow-400 font-bold'
  return 'text-green-400'
}
function sslStatusText(s) {
  return { healthy: '正常', warning: '即将过期', critical: '紧急', expired: '已过期', error: '错误' }[s] || s || '--'
}
function sslStatusBadge(s) {
  return { healthy: 'bg-green-900/40 text-green-400', warning: 'bg-yellow-900/40 text-yellow-400', critical: 'bg-red-900/40 text-red-400', expired: 'bg-red-900/60 text-red-300', error: 'bg-dark-300 text-text-tertiary' }[s] || 'bg-dark-300 text-text-tertiary'
}
function feishuText(s) {
  return { healthy: '正常', disabled: '已禁用', not_configured: '未配置' }[s] || s || '--'
}

function formatLastSeen(timestamp) {
  if (!timestamp) return '--'
  const now = new Date()
  const then = new Date(timestamp)
  const diffMs = now - then
  const diffSec = Math.floor(diffMs / 1000)

  if (diffSec < 60) return `${diffSec}秒前`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}小时前`
  return `${Math.floor(diffSec / 86400)}天前`
}

async function restartMT5Instance(client) {
  // TODO: 实现重启功能
  // 需要先获取实例信息，然后调用重启 API
  console.log('Restart MT5 instance for client:', client.client_id)
  alert('重启功能开发中，请前往用户管理页面操作')
}

function viewMT5Details(client) {
  // 跳转到用户管理页面的 MT5 客户端 tab
  window.location.href = '/users?tab=mt5&client=' + client.client_id
}

onMounted(() => {
  refreshAll()
  timer = setInterval(refreshAll, 10000)  // 10秒刷新全局状态
  mt5Timer = setInterval(fetchMonitorStatus, 5000)  // 5秒刷新 MT5 客户端状态
})
onUnmounted(() => {
  clearInterval(timer)
  clearInterval(mt5Timer)
})
</script>
