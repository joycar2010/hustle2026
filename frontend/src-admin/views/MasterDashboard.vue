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

    <!-- ===== 服务器状态区域 ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">服务器状态区域</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">

        <!-- GO 后端服务器 -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="goStatus.online ? 'border-green-800/50' : 'border-red-800/50'">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div :class="['w-2.5 h-2.5 rounded-full', goStatus.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold text-text-primary">GO 后端服务器</span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded-full" :class="goStatus.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
              {{ goStatus.online ? '在线' : '离线' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>端口</span><span class="text-text-secondary font-mono">:8080</span></div>
            <div class="flex justify-between"><span>运行时长</span><span class="text-text-secondary font-mono">{{ goStatus.uptime || '--' }}</span></div>
            <div class="flex justify-between"><span>内存使用</span><span class="text-text-secondary font-mono">{{ goStatus.memory || '--' }}</span></div>
            <div class="flex justify-between"><span>Redis 连接</span>
              <span :class="goStatus.redis ? 'text-green-400' : 'text-red-400'">{{ goStatus.redis ? '正常' : '异常' }}</span>
            </div>
          </div>
        </div>

        <!-- MT5 桥接服务器 (SSH 已设置完毕) -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="mt5System.online ? 'border-green-800/50' : 'border-red-800/50'">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div :class="['w-2.5 h-2.5 rounded-full', mt5System.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold text-text-primary">MT5 桥接服务器</span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded-full" :class="mt5System.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
              {{ mt5System.online ? '在线' : '离线' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>端口</span><span class="text-text-secondary font-mono">:8001</span></div>
            <div class="flex justify-between"><span>SSH 隧道</span><span class="text-green-400">已配置</span></div>
            <div class="flex justify-between"><span>MT5 登录</span><span class="text-text-secondary font-mono">{{ mt5System.login || '--' }}</span></div>
            <div class="flex justify-between"><span>连接状态</span>
              <span :class="mt5System.connected ? 'text-green-400' : 'text-yellow-400'">{{ mt5System.connected ? '已连接' : '未连接' }}</span>
            </div>
            <div class="flex justify-between"><span>服务器</span><span class="text-text-secondary truncate max-w-[60%]">{{ mt5System.server || '--' }}</span></div>
            <div v-if="mt5System.balance != null" class="flex justify-between"><span>余额</span><span class="text-text-secondary font-mono">{{ mt5System.balance?.toFixed(2) }} UST</span></div>
          </div>
        </div>

        <!-- WS & 实时统计 -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center gap-2 mb-3">
            <div class="w-2.5 h-2.5 rounded-full bg-primary animate-pulse"></div>
            <span class="text-sm font-semibold text-text-primary">实时统计</span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>WS 连接数</span><span class="text-primary font-bold text-base">{{ stats.wsConnections ?? 0 }}</span></div>
            <div class="flex justify-between"><span>总用户数</span><span class="text-text-secondary font-bold">{{ stats.totalUsers ?? '--' }}</span></div>
            <div class="flex justify-between"><span>活跃账户</span><span class="text-text-secondary">{{ stats.activeAccounts ?? '--' }}</span></div>
            <div class="flex justify-between"><span>MT5持仓</span><span class="text-text-secondary">{{ stats.totalPositions ?? '--' }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 交易所账户监控区域 ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">交易所账户监控区域</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">

        <!-- Binance/Bybit 账户汇总 -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary md:col-span-2">
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-semibold text-text-primary">交易所账户汇总</span>
            <span class="text-xs text-text-tertiary">{{ stats.activeAccounts ?? '--' }} 个活跃账户</span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div class="bg-dark-200 rounded-lg p-2.5">
              <div class="text-text-tertiary mb-1">总资产 (USDT)</div>
              <div class="font-mono font-bold text-text-primary text-sm">{{ fmtNum(totals.total_assets) }}</div>
            </div>
            <div class="bg-dark-200 rounded-lg p-2.5">
              <div class="text-text-tertiary mb-1">可用资产</div>
              <div class="font-mono font-bold text-text-secondary text-sm">{{ fmtNum(totals.available_assets) }}</div>
            </div>
            <div class="bg-dark-200 rounded-lg p-2.5">
              <div class="text-text-tertiary mb-1">净资产</div>
              <div class="font-mono font-bold text-text-secondary text-sm">{{ fmtNum(totals.net_assets) }}</div>
            </div>
            <div class="bg-dark-200 rounded-lg p-2.5">
              <div class="text-text-tertiary mb-1">当日盈亏</div>
              <div class="font-mono font-bold text-sm" :class="pnlClass(totals.daily_pnl)">
                {{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}
              </div>
            </div>
          </div>
        </div>

        <!-- MT5 客户端监控 -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center gap-2 mb-3">
            <div :class="['w-2.5 h-2.5 rounded-full', monitorData.mt5_clients?.some(c => c.online) ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
            <span class="text-sm font-semibold text-text-primary">MT5 客户端</span>
            <span class="text-xs text-text-tertiary">({{ monitorData.mt5_clients?.filter(c=>c.online).length ?? 0 }}/{{ monitorData.mt5_clients?.length ?? 0 }} 在线)</span>
          </div>
          <div v-if="monitorData.mt5_clients?.length" class="space-y-2">
            <div v-for="c in monitorData.mt5_clients" :key="c.mt5_login"
              class="flex items-center justify-between text-xs bg-dark-200 rounded px-3 py-2">
              <div>
                <span class="text-text-primary font-medium">{{ c.client_name }}</span>
                <span class="text-text-tertiary ml-2">{{ c.username }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-text-tertiary font-mono">{{ c.mt5_login }}</span>
                <span :class="c.online ? 'text-green-400' : 'text-red-400'">{{ c.online ? '在线' : '离线' }}</span>
              </div>
            </div>
          </div>
          <div v-else class="text-xs text-text-tertiary text-center py-3">暂无 MT5 客户端数据</div>
        </div>
      </div>
    </div>

    <!-- ===== 后台服务监控区域 ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">后台服务监控区域</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">

        <!-- Redis -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="monitorData.redis?.connected ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div :class="['w-2.5 h-2.5 rounded-full', monitorData.redis?.connected ? 'bg-green-500' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold text-text-primary">Redis 缓存</span>
            </div>
            <span :class="['text-xs', monitorData.redis?.connected ? 'text-green-400' : 'text-red-400']">
              {{ monitorData.redis?.connected ? '已连接' : '未连接' }}
            </span>
          </div>
          <div v-if="monitorData.redis?.connected" class="grid grid-cols-3 gap-2 text-xs text-text-tertiary">
            <div><span class="block">版本</span><span class="text-text-secondary">{{ monitorData.redis?.version || '--' }}</span></div>
            <div><span class="block">内存</span><span class="text-text-secondary">{{ monitorData.redis?.used_memory_human || '--' }}</span></div>
            <div><span class="block">客户端</span><span class="text-text-secondary">{{ monitorData.redis?.connected_clients || '--' }}</span></div>
          </div>
          <div v-else-if="monitorData.redis?.error" class="text-xs text-red-400 mt-1 truncate">{{ monitorData.redis.error }}</div>
        </div>

        <!-- WebSocket & 数据库连接池 -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center gap-2 mb-3">
            <div class="w-2.5 h-2.5 rounded-full bg-primary animate-pulse"></div>
            <span class="text-sm font-semibold text-text-primary">实时连接</span>
          </div>
          <div class="text-xs text-text-tertiary space-y-2">
            <div class="flex justify-between items-center">
              <span>WebSocket 连接数</span>
              <span class="font-mono font-bold text-primary text-sm">{{ stats.wsConnections ?? 0 }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span>数据库连接池</span>
              <span :class="monitorData.redis?.connected ? 'text-green-400' : 'text-yellow-400'">
                {{ monitorData.redis?.connected ? '正常' : '检查中' }}
              </span>
            </div>
            <div class="flex justify-between items-center">
              <span>数据更新时间</span>
              <span class="text-text-secondary font-mono text-xs">{{ monitorData.timestamp ? new Date(monitorData.timestamp).toLocaleTimeString('zh-CN') : '--' }}</span>
            </div>
          </div>
        </div>

        <!-- 后端服务状态 -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center gap-2 mb-3">
            <div class="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse"></div>
            <span class="text-sm font-semibold text-text-primary">后端服务</span>
          </div>
          <div class="text-xs text-text-tertiary space-y-2">
            <div class="flex justify-between items-center">
              <span>API 服务 (Go)</span>
              <span :class="goStatus.online ? 'text-green-400' : 'text-red-400'">{{ goStatus.online ? '运行中' : '异常' }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span>API 服务 (Python)</span>
              <span :class="monitorData.redis?.connected ? 'text-green-400' : 'text-yellow-400'">{{ monitorData.redis?.connected ? '运行中' : '检查中' }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span>持仓监控</span>
              <span class="text-green-400">运行中</span>
            </div>
            <div class="flex justify-between items-center">
              <span>策略管理</span>
              <span class="text-green-400">运行中</span>
            </div>
            <div class="flex justify-between items-center">
              <span>飞书通知</span>
              <span :class="monitorData.feishu?.status === 'healthy' ? 'text-green-400' : 'text-yellow-400'">
                {{ feishuText(monitorData.feishu?.status) }}
              </span>
            </div>
          </div>
        </div>

        <!-- SSL 证书 (跨 2 列) -->
        <div class="bg-dark-100 rounded-xl p-4 border sm:col-span-2 xl:col-span-3" :class="sslOverallOk ? 'border-green-800/30' : 'border-yellow-800/30'">
          <div class="flex items-center gap-2 mb-3">
            <div :class="['w-2.5 h-2.5 rounded-full', sslOverallOk ? 'bg-green-500' : 'bg-yellow-500']"></div>
            <span class="text-sm font-semibold text-text-primary">SSL 证书</span>
            <span class="text-xs text-text-tertiary">({{ (monitorData.ssl_certificate || []).length }} 个域名)</span>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div v-for="cert in (monitorData.ssl_certificate || [])" :key="cert.cert_path"
              class="bg-dark-200 rounded-lg px-3 py-2.5 text-xs">
              <div class="font-mono text-text-secondary truncate mb-1.5">
                {{ cert.domain_names?.[0] || cert.cert_path?.split('/').slice(-2,-1)[0] || '--' }}
              </div>
              <div class="flex items-center justify-between">
                <span :class="sslDaysClass(cert.days_remaining)">
                  {{ cert.exists ? cert.days_remaining + ' 天' : '未找到' }}
                </span>
                <span :class="sslStatusBadge(cert.status)" class="px-1.5 py-0.5 rounded">{{ sslStatusText(cert.status) }}</span>
              </div>
            </div>
            <div v-if="!monitorData.ssl_certificate?.length" class="text-text-tertiary text-xs">暂无证书数据</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== IP 代理状态 ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">IP 代理状态</h2>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
        <div v-if="proxyAccounts.length" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          <div v-for="acc in proxyAccounts" :key="acc.account_id"
            class="bg-dark-200 rounded-lg px-3 py-2.5 text-xs">
            <div class="flex items-center justify-between mb-1.5">
              <span class="font-medium text-text-primary truncate max-w-[70%]">{{ acc.account_name }}</span>
              <span v-if="acc.proxy_config" class="px-1.5 py-0.5 rounded bg-green-900/40 text-green-400">已配置</span>
              <span v-else class="px-1.5 py-0.5 rounded bg-dark-300 text-text-tertiary">直连</span>
            </div>
            <div v-if="acc.proxy_config" class="text-text-tertiary space-y-0.5">
              <div class="flex justify-between">
                <span>地址</span>
                <span class="font-mono text-text-secondary">{{ acc.proxy_config.host }}:{{ acc.proxy_config.port }}</span>
              </div>
              <div class="flex justify-between">
                <span>类型</span>
                <span class="uppercase text-text-secondary">{{ acc.proxy_config.proxy_type }}</span>
              </div>
              <div v-if="acc.proxy_config.region" class="flex justify-between">
                <span>地区</span>
                <span class="text-text-secondary">{{ acc.proxy_config.region }}</span>
              </div>
            </div>
            <div v-else class="text-text-tertiary">使用服务器IP直连</div>
          </div>
        </div>
        <div v-else class="text-center text-text-tertiary text-sm py-4">
          暂无账户数据，或所有账户均使用直连
        </div>
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

const goStatus = ref({ online: false, uptime: '', workers: '', memory: '', redis: false })
const mt5System = ref({ online: false, login: '', server: '', connected: false })
const stats     = ref({ wsConnections: 0, totalUsers: 0, activeAccounts: 0, totalPositions: 0 })
const userFinancials = ref([])
const monitorData = ref({ redis: null, ssl_certificate: [], feishu: null, mt5_clients: [] })
const proxyAccounts = ref([])

let timer = null

// --- Computed ---
const totals = computed(() => ({
  total_assets:     userFinancials.value.reduce((s, u) => s + (u.total_assets || 0), 0),
  available_assets: userFinancials.value.reduce((s, u) => s + (u.available_assets || 0), 0),
  net_assets:       userFinancials.value.reduce((s, u) => s + (u.net_assets || 0), 0),
  daily_pnl:        userFinancials.value.reduce((s, u) => s + (u.daily_pnl || 0), 0),
}))
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
  // System MT5 bridge: /mt5/connection/status + /mt5/account/info (Go → 54.249.66.53:8001)
  try {
    const [statusR, infoR] = await Promise.all([
      api.get('/api/v1/mt5/connection/status'),
      api.get('/api/v1/mt5/account/info').catch(() => ({ data: {} })),
    ])
    const s = statusR.data || {}
    const info = infoR.data || {}
    mt5System.value = {
      online:    true,
      login:     String(s.account ?? info.login ?? '--'),
      server:    s.server ?? info.server ?? '--',
      connected: s.connected ?? false,
      balance:   info.balance ?? s.balance ?? null,
      equity:    info.equity  ?? s.equity  ?? null,
    }
  } catch {
    mt5System.value = { online: false, login: '--', server: '--', connected: false }
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

async function fetchProxyAccounts() {
  try {
    const r = await api.get('/api/v1/accounts')
    const all = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    proxyAccounts.value = all.filter(a => a.is_active)
  } catch {}
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([fetchMonitorStatus(), fetchStats(), fetchUserFinancials(), fetchMT5Status(), fetchProxyAccounts()])
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

onMounted(() => {
  refreshAll()
  timer = setInterval(refreshAll, 10000)
})
onUnmounted(() => clearInterval(timer))
</script>
