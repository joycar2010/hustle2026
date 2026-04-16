<template>
  <div class="container mx-auto px-4 py-6 space-y-5">

    <!-- ===== Layer 0: Global Health Bar ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary px-5 py-3 flex items-center justify-between flex-wrap gap-3">
      <div class="flex items-center gap-4">
        <h1 class="text-xl font-bold text-text-primary">总控面板</h1>
        <div class="flex items-center gap-1.5">
          <div class="w-2.5 h-2.5 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-red-500'"></div>
          <span class="text-xs" :class="wsConnected ? 'text-green-400' : 'text-red-400'">
            {{ wsConnected ? 'WebSocket 实时' : 'HTTP 回退' }}
          </span>
        </div>
      </div>
      <div class="flex items-center gap-5 text-xs">
        <div class="flex items-center gap-1.5">
          <span class="text-text-tertiary">WS连接</span>
          <span class="font-mono font-bold text-primary">{{ stats.wsConnections ?? 0 }}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-text-tertiary">活跃账户</span>
          <span class="font-mono font-bold">{{ stats.activeAccounts ?? 0 }}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-text-tertiary">总净值</span>
          <span class="font-mono font-bold text-text-primary">{{ fmtNum(totals.net_assets) }}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-text-tertiary">日PnL</span>
          <span class="font-mono font-bold" :class="pnlClass(totals.daily_pnl)">
            {{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}
          </span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-text-tertiary">风险</span>
          <span class="px-1.5 py-0.5 rounded text-xs font-bold" :class="globalRiskBadge">{{ globalRiskText }}</span>
        </div>
        <span class="text-text-tertiary">{{ lastUpdate }}</span>
        <button @click="refreshAll" :disabled="refreshing" class="px-2.5 py-1 bg-dark-200 hover:bg-dark-50 rounded-lg text-xs transition-colors disabled:opacity-50">
          <span :class="refreshing && 'animate-spin inline-block'">⟳</span> 刷新
        </button>
      </div>
    </div>

    <!-- ===== Layer 1: SSL Certificates (compact) ===== -->
    <div class="bg-dark-100 rounded-xl border px-4 py-3 flex items-center gap-4 flex-wrap" :class="sslOverallOk ? 'border-green-800/30' : 'border-yellow-800/30'">
      <div class="flex items-center gap-2">
        <div :class="['w-2 h-2 rounded-full', sslOverallOk ? 'bg-green-500' : 'bg-yellow-500']"></div>
        <span class="text-sm font-semibold">SSL 证书</span>
      </div>
      <div class="flex gap-4">
        <div v-for="cert in (monitorData.ssl_certificate || [])" :key="cert.cert_path" class="flex items-center gap-2 text-xs">
          <span class="font-mono text-text-secondary">{{ cert.domain_names?.[0] || '--' }}</span>
          <span :class="sslDaysClass(cert.days_remaining)" class="font-bold">{{ cert.exists ? cert.days_remaining + '天' : '未找到' }}</span>
          <span :class="sslStatusBadge(cert.status)" class="px-1.5 py-0.5 rounded">{{ sslStatusText(cert.status) }}</span>
        </div>
      </div>
    </div>

    <!-- ===== Layer 2: Fund & Risk Core ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">资金与风控</h2>

      <!-- Fund summary cards -->
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">总资产 (USDT)</div>
          <div class="font-mono font-bold text-lg text-text-primary">{{ fmtNum(totals.total_assets) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">可用资产</div>
          <div class="font-mono font-bold text-lg text-text-secondary">{{ fmtNum(totals.available_assets) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">净资产</div>
          <div class="font-mono font-bold text-lg text-text-secondary">{{ fmtNum(totals.net_assets) }}</div>
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">当日盈亏</div>
          <div class="font-mono font-bold text-lg" :class="pnlClass(totals.daily_pnl)">
            {{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}
          </div>
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">持仓数 / 用户数</div>
          <div class="font-mono font-bold text-lg text-primary">{{ stats.totalPositions ?? 0 }} / {{ stats.totalUsers ?? 0 }}</div>
        </div>
      </div>

      <!-- Per-account health matrix -->
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
        <div v-for="acc in sortedAccounts" :key="acc.account_id"
          class="bg-dark-100 rounded-xl p-4 border transition-all"
          :class="accBorderClass(acc)">
          <div class="flex items-start justify-between mb-2">
            <div class="flex-1 min-w-0">
              <div class="font-semibold text-sm text-text-primary truncate">{{ acc.account_name }}</div>
              <div class="flex items-center gap-1.5 mt-0.5">
                <span class="px-1.5 py-0.5 rounded text-[10px]" :class="acc.is_mt5_account ? 'bg-purple-900/40 text-purple-300' : 'bg-blue-900/40 text-blue-300'">
                  {{ acc.is_mt5_account ? 'MT5' : platformName(acc.platform_id) }}
                </span>
                <span v-if="acc.account_role" class="px-1.5 py-0.5 rounded text-[10px] bg-yellow-900/40 text-yellow-300">
                  {{ acc.account_role === 'primary' ? '主' : '对冲' }}
                </span>
                <span class="text-[10px] text-text-tertiary">{{ accOwnerName(acc) }}</span>
              </div>
            </div>
            <div class="text-right flex-shrink-0">
              <div class="text-xs text-text-tertiary">日PnL</div>
              <div class="font-mono font-bold text-sm" :class="pnlClass(acc.daily_pnl || acc.balance?.daily_pnl)">
                {{ pnlStr(acc.daily_pnl || acc.balance?.daily_pnl) }}
              </div>
            </div>
          </div>
          <!-- Alert tag -->
          <div v-if="acc._error" class="text-[10px] text-red-400 bg-red-900/20 rounded px-2 py-0.5 mb-2 truncate">{{ acc._error }}</div>
          <div v-if="accRiskLevel(acc) === 'danger'" class="text-[10px] text-red-400 bg-red-900/20 rounded px-2 py-0.5 mb-2">保证金率过高</div>
          <!-- Data grid -->
          <div class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <div class="flex justify-between"><span class="text-text-tertiary">净资产</span><span class="font-mono text-text-primary">{{ fmtNum(getBal(acc, 'net_assets')) }}</span></div>
            <div class="flex justify-between"><span class="text-text-tertiary">可用</span><span class="font-mono text-text-secondary">{{ fmtNum(getBal(acc, 'available_balance')) }}</span></div>
            <div class="flex justify-between"><span class="text-text-tertiary">浮盈亏</span><span class="font-mono" :class="pnlClass(getBal(acc, 'unrealized_pnl'))">{{ pnlStr(getBal(acc, 'unrealized_pnl')) }}</span></div>
            <div class="flex justify-between">
              <span class="text-text-tertiary">保证金率</span>
              <span class="font-mono" :class="riskClass(getBal(acc, 'risk_ratio'))">{{ getBal(acc, 'risk_ratio') != null ? getBal(acc, 'risk_ratio').toFixed(1) + '%' : '--' }}</span>
            </div>
          </div>
          <!-- Position count -->
          <div v-if="(acc.positions || []).length" class="mt-2 pt-1.5 border-t border-border-secondary flex justify-between text-xs">
            <span class="text-text-tertiary">持仓</span>
            <span class="font-mono text-primary font-bold">{{ acc.positions.length }} 笔</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Layer 2b: Hedge Exposure Monitor ===== -->
    <div v-if="hedgingPairs.length" class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">对冲敞口监控</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5 gap-3">
        <div v-for="pair in hedgingPairs" :key="pair.pair_code"
          class="bg-dark-100 rounded-xl p-4 border"
          :class="pair.is_active ? 'border-border-primary' : 'border-red-900/30 opacity-60'">
          <div class="flex items-center justify-between mb-2">
            <span class="font-bold text-base text-text-primary">{{ pair.pair_code }}</span>
            <span class="px-1.5 py-0.5 rounded text-[10px]"
              :class="pair.is_active ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'">
              {{ pair.is_active ? '活跃' : '停用' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>CEX</span><span class="font-mono text-text-secondary">{{ pair.symbol_a?.symbol || '--' }}</span></div>
            <div class="flex justify-between"><span>MT5</span><span class="font-mono text-text-secondary">{{ pair.symbol_b?.symbol || '--' }}</span></div>
            <div class="flex justify-between"><span>转换因子</span><span class="font-mono text-primary font-bold">{{ pair.conversion_factor || '--' }}</span></div>
            <div class="flex justify-between"><span>平台</span><span class="text-text-secondary">{{ pair.platform_a?.platform_name || 'Binance' }} / {{ pair.platform_b?.platform_name || 'MT5' }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Layer 3: Infrastructure ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">基础设施</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">

        <!-- API Service -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="goStatus.online ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <div :class="['w-2 h-2 rounded-full', goStatus.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold">后端 API 服务器</span>
            </div>
            <span class="text-[10px] px-1.5 py-0.5 rounded-full" :class="goStatus.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
              {{ goStatus.online ? '在线' : '离线' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-0.5">
            <div class="flex justify-between"><span>端口</span><span class="font-mono text-text-secondary">:8000 / :8080</span></div>
            <div class="flex justify-between"><span>运行</span><span class="font-mono text-text-secondary">{{ goStatus.uptime || '--' }}</span></div>
            <div class="flex justify-between"><span>内存</span><span class="font-mono text-text-secondary">{{ goStatus.memory || '--' }}</span></div>
          </div>
        </div>

        <!-- MT5 Bridge + Clients merged -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="mt5System.online ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <div :class="['w-2 h-2 rounded-full', mt5System.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold">MT5 Bridge 服务器</span>
            </div>
            <span class="text-[10px]" :class="mt5System.online ? 'text-green-400' : 'text-red-400'">
              {{ mt5ClientsOnline }}/{{ mt5ClientsTotal }} 在线
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-0.5">
            <div class="flex justify-between"><span>运行</span><span class="font-mono text-text-secondary">{{ mt5System.uptime || '--' }}</span></div>
            <div class="flex justify-between"><span>内存</span><span class="font-mono text-text-secondary">{{ mt5System.memory || '--' }}</span></div>
            <div class="flex justify-between"><span>实例</span><span class="font-mono text-text-secondary">{{ mt5System.instances ?? '--' }}</span></div>
          </div>
          <!-- MT5 client list -->
          <div v-if="monitorData.mt5_clients?.length" class="mt-2 pt-1.5 border-t border-border-secondary space-y-1">
            <div v-for="c in monitorData.mt5_clients" :key="c.mt5_login" class="flex items-center justify-between text-[10px]">
              <div class="flex items-center gap-1 truncate">
                <span class="text-text-secondary">{{ c.client_name }}</span>
                <span v-if="c.is_system_service" class="px-0.5 text-purple-400">SYS</span>
              </div>
              <div class="flex items-center gap-1.5">
                <span class="text-text-tertiary font-mono">{{ c.mt5_login }}</span>
                <div :class="['w-1.5 h-1.5 rounded-full', isMT5Online(c) ? 'bg-green-500' : 'bg-red-500']"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Redis + DB + WS merged -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="monitorData.redis?.connected ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <div :class="['w-2 h-2 rounded-full', monitorData.redis?.connected ? 'bg-green-500' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold">数据层</span>
            </div>
            <span class="text-[10px]" :class="monitorData.redis?.connected ? 'text-green-400' : 'text-red-400'">
              {{ monitorData.redis?.connected ? '正常' : '异常' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-0.5">
            <div class="flex justify-between"><span>Redis</span><span class="font-mono text-text-secondary">v{{ monitorData.redis?.version || '--' }} / {{ monitorData.redis?.used_memory_human || '--' }}</span></div>
            <div class="flex justify-between"><span>客户端</span><span class="font-mono text-text-secondary">{{ monitorData.redis?.connected_clients || '--' }}</span></div>
            <div class="flex justify-between"><span>WS连接</span><span class="font-mono text-primary font-bold">{{ stats.wsConnections ?? 0 }}</span></div>
            <div class="flex justify-between"><span>数据库</span><span :class="monitorData.redis?.connected ? 'text-green-400' : 'text-yellow-400'">正常</span></div>
          </div>
        </div>

        <!-- Backend Services -->
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="flex items-center gap-2 mb-2">
            <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            <span class="text-sm font-semibold">后端服务</span>
          </div>
          <div class="text-xs text-text-tertiary space-y-0.5">
            <div class="flex justify-between"><span>API 服务</span><span :class="goStatus.online ? 'text-green-400' : 'text-red-400'">{{ goStatus.online ? '运行中' : '异常' }}</span></div>
            <div class="flex justify-between"><span>MT5 Bridge</span><span :class="mt5System.online ? 'text-green-400' : 'text-red-400'">{{ mt5System.online ? '运行中' : '异常' }}</span></div>
            <div class="flex justify-between"><span>持仓监控</span><span class="text-green-400">运行中</span></div>
            <div class="flex justify-between"><span>飞书通知</span>
              <span :class="monitorData.feishu?.status === 'healthy' ? 'text-green-400' : monitorData.feishu?.status === 'disabled' ? 'text-yellow-400' : 'text-text-tertiary'">
                {{ feishuText(monitorData.feishu?.status) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Layer 4: IP Proxy ===== -->
    <div v-if="proxyAccounts.length" class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">IP 代理状态</h2>
      <div class="bg-dark-100 rounded-xl border border-border-primary p-4">
        <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          <div v-for="acc in proxyAccounts" :key="acc.account_id"
            class="bg-dark-200 rounded-lg px-3 py-2.5 text-xs">
            <div class="flex items-center justify-between mb-1">
              <span class="font-medium text-text-primary truncate max-w-[60%]">{{ acc.account_name }}</span>
              <span v-if="acc.proxy_config" class="px-1.5 py-0.5 rounded" :class="proxyStatusClass(acc.proxy_config.ip_status || proxyIPStatus(acc))">
                {{ proxyStatusText(acc.proxy_config.ip_status || proxyIPStatus(acc)) }}
              </span>
            </div>
            <div v-if="acc.proxy_config" class="text-text-tertiary space-y-0.5">
              <div class="flex justify-between"><span>地址</span><span class="font-mono text-text-secondary">{{ acc.proxy_config.host }}:{{ acc.proxy_config.port }}</span></div>
              <div class="flex justify-between"><span>类型</span><span class="uppercase text-text-secondary">{{ acc.proxy_config.proxy_type || 'SOCKS5' }}</span></div>
              <div v-if="acc.proxy_config.region" class="flex justify-between"><span>地区</span><span class="text-text-secondary">{{ acc.proxy_config.region }}</span></div>
              <div v-if="acc.proxy_config.allocated_at" class="flex justify-between"><span>分配时间</span><span class="font-mono text-text-secondary">{{ acc.proxy_config.allocated_at }}</span></div>
              <div v-if="acc.proxy_config.expires_at" class="flex justify-between">
                <span>过期时间</span>
                <span class="font-mono" :class="proxyDaysClass(proxyDaysLeft(acc))">{{ acc.proxy_config.expires_at }} ({{ proxyDaysLeft(acc) }}天)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Layer 5: User Fund Table ===== -->
    <div class="bg-dark-100 rounded-xl border border-border-primary">
      <div class="flex items-center justify-between px-5 py-3 border-b border-border-secondary">
        <h2 class="text-sm font-semibold text-text-primary">用户实时资金状态</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs text-text-tertiary">{{ wsConnected ? 'WS实时' : '10s轮询' }}</span>
          <div class="w-2 h-2 rounded-full animate-pulse" :class="wsConnected ? 'bg-green-500' : 'bg-yellow-500'"></div>
        </div>
      </div>
      <!-- Desktop -->
      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[800px]">
          <thead><tr class="border-b border-border-secondary text-text-tertiary text-xs">
            <th class="text-left px-5 py-2.5">用户名</th>
            <th class="text-left px-3 py-2.5">角色</th>
            <th class="text-right px-3 py-2.5">账户数</th>
            <th class="text-right px-3 py-2.5">总资产</th>
            <th class="text-right px-3 py-2.5">净资产</th>
            <th class="text-right px-3 py-2.5">当日PnL</th>
            <th class="text-right px-5 py-2.5">风险率</th>
          </tr></thead>
          <tbody>
            <tr v-if="usersLoading"><td colspan="7" class="text-center py-10 text-text-tertiary">加载中...</td></tr>
            <tr v-else-if="!userFinancials.length"><td colspan="7" class="text-center py-10 text-text-tertiary">暂无数据</td></tr>
            <tr v-for="u in userFinancials" :key="u.user_id" class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
              <td class="px-5 py-2.5 font-medium text-text-primary">{{ u.username }}</td>
              <td class="px-3 py-2.5"><span class="px-1.5 py-0.5 rounded text-xs" :class="roleBadgeClass(u.role)">{{ u.role || '--' }}</span></td>
              <td class="px-3 py-2.5 text-right text-text-secondary">{{ u.account_count ?? '--' }}</td>
              <td class="px-3 py-2.5 text-right font-mono font-semibold">{{ fmtNum(u.total_assets) }}</td>
              <td class="px-3 py-2.5 text-right font-mono text-text-secondary">{{ fmtNum(u.net_assets) }}</td>
              <td class="px-3 py-2.5 text-right font-mono font-semibold" :class="pnlClass(u.daily_pnl)">
                {{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}
              </td>
              <td class="px-5 py-2.5 text-right"><span :class="riskClass(u.risk_rate)">{{ u.risk_rate != null ? u.risk_rate.toFixed(1) + '%' : '--' }}</span></td>
            </tr>
          </tbody>
          <tfoot v-if="userFinancials.length" class="border-t-2 border-border-primary">
            <tr class="bg-dark-50 text-sm font-semibold">
              <td class="px-5 py-2.5 text-text-secondary" colspan="3">合计</td>
              <td class="px-3 py-2.5 text-right font-mono">{{ fmtNum(totals.total_assets) }}</td>
              <td class="px-3 py-2.5 text-right font-mono text-text-secondary">{{ fmtNum(totals.net_assets) }}</td>
              <td class="px-3 py-2.5 text-right font-mono" :class="pnlClass(totals.daily_pnl)">{{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}</td>
              <td class="px-5 py-2.5"></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <!-- Mobile -->
      <div class="md:hidden space-y-2 p-3">
        <div v-if="usersLoading" class="text-center py-8 text-text-tertiary text-sm">加载中...</div>
        <div v-for="u in userFinancials" :key="u.user_id" class="bg-dark-200 rounded-xl p-3 space-y-2 border border-border-secondary">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="font-bold text-sm">{{ u.username }}</span>
              <span class="px-1.5 py-0.5 rounded text-xs" :class="roleBadgeClass(u.role)">{{ u.role }}</span>
            </div>
            <span class="font-mono font-bold text-sm" :class="pnlClass(u.daily_pnl)">{{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}</span>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="bg-dark-300 rounded p-2"><div class="text-text-tertiary mb-0.5">总资产</div><div class="font-mono font-bold">{{ fmtNum(u.total_assets) }}</div></div>
            <div class="bg-dark-300 rounded p-2"><div class="text-text-tertiary mb-0.5">净资产</div><div class="font-mono">{{ fmtNum(u.net_assets) }}</div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from '@/composables/useWebSocket.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'

// --- WebSocket ---
const { connected: wsConnected, lastMessage, connect: wsConnect, disconnect: wsDisconnect } = useWebSocket()
let fallbackTimer = null

// --- State ---
const refreshing = ref(false)
const usersLoading = ref(true)
const lastUpdate = ref('--')

const goStatus = ref({ online: false, uptime: '', memory: '', redis: false })
const mt5System = ref({ online: false })
const stats = ref({ wsConnections: 0, totalUsers: 0, activeAccounts: 0, totalPositions: 0 })
const allAccounts = ref([])
const userFinancials = ref([])
const monitorData = ref({ redis: null, ssl_certificate: [], feishu: null, mt5_clients: [] })
const proxyAccounts = ref([])
const hedgingPairs = ref([])
const usersMap = ref({})

// --- WS message handler ---
watch(lastMessage, (msg) => {
  if (!msg) return
  if (msg.type === 'account_balance' && msg.data) {
    applyAccountBalance(msg.data)
  }
  if (msg.type === 'redis_status' && msg.data) {
    monitorData.value.redis = msg.data
  }
  if (msg.type === 'position_update' && msg.data) {
    // Refresh positions count
    stats.value.totalPositions = msg.data.total_positions ?? stats.value.totalPositions
  }
})

// Fallback: when WS disconnects, poll via HTTP
watch(wsConnected, (val) => {
  if (val) {
    clearInterval(fallbackTimer); fallbackTimer = null
  } else if (!fallbackTimer) {
    fallbackTimer = setInterval(refreshAll, 10000)
  }
})

function applyAccountBalance(d) {
  if (d.summary) {
    stats.value.activeAccounts = d.summary.account_count ?? stats.value.activeAccounts
    stats.value.totalPositions = d.summary.position_count ?? stats.value.totalPositions
  }
  const accs = []
  if (d.accounts && Array.isArray(d.accounts)) accs.push(...d.accounts)
  if (d.failed_accounts && Array.isArray(d.failed_accounts)) {
    for (const fa of d.failed_accounts) accs.push({ ...fa, _error: fa.error || '获取失败' })
  }
  if (accs.length) {
    allAccounts.value = accs
    rebuildUserFinancials()
  }
  lastUpdate.value = dayjs().format('HH:mm:ss')
}

function rebuildUserFinancials() {
  const map = {}
  for (const [uid, u] of Object.entries(usersMap.value)) {
    map[uid] = { ...u, account_count: 0, total_assets: 0, available_assets: 0, net_assets: 0, daily_pnl: 0, risk_rate: null }
  }
  for (const acc of allAccounts.value) {
    const uid = acc.user_id
    if (uid && map[uid]) {
      const b = acc.balance || {}
      map[uid].account_count++
      map[uid].total_assets += b.total_assets || 0
      map[uid].available_assets += b.available_balance || 0
      map[uid].net_assets += b.net_assets || 0
      map[uid].daily_pnl += acc.daily_pnl || b.daily_pnl || 0
      if (b.risk_ratio != null) map[uid].risk_rate = b.risk_ratio
    }
  }
  userFinancials.value = Object.values(map)
}

// --- Computed ---
const totals = computed(() => ({
  total_assets: userFinancials.value.reduce((s, u) => s + (u.total_assets || 0), 0),
  available_assets: userFinancials.value.reduce((s, u) => s + (u.available_assets || 0), 0),
  net_assets: userFinancials.value.reduce((s, u) => s + (u.net_assets || 0), 0),
  daily_pnl: userFinancials.value.reduce((s, u) => s + (u.daily_pnl || 0), 0),
}))

const sslOverallOk = computed(() =>
  (monitorData.value.ssl_certificate || []).every(c => c.status !== 'expired' && c.status !== 'critical')
)

const sortedAccounts = computed(() => {
  return [...allAccounts.value].sort((a, b) => {
    // Errors first
    if (a._error && !b._error) return -1
    if (!a._error && b._error) return 1
    // High risk first
    const rA = getBal(a, 'risk_ratio') ?? 0
    const rB = getBal(b, 'risk_ratio') ?? 0
    if (rA > 70 && rB <= 70) return -1
    if (rB > 70 && rA <= 70) return 1
    // By net assets desc
    return (getBal(b, 'net_assets') || 0) - (getBal(a, 'net_assets') || 0)
  })
})

const mt5ClientsOnline = computed(() => (monitorData.value.mt5_clients || []).filter(c => isMT5Online(c)).length)
const mt5ClientsTotal = computed(() => (monitorData.value.mt5_clients || []).length)

const globalRiskText = computed(() => {
  const maxRisk = Math.max(...allAccounts.value.map(a => getBal(a, 'risk_ratio') || 0), 0)
  if (maxRisk > 80) return '高风险'
  if (maxRisk > 50) return '中等'
  return '正常'
})
const globalRiskBadge = computed(() => {
  const t = globalRiskText.value
  if (t === '高风险') return 'bg-red-900/40 text-red-400'
  if (t === '中等') return 'bg-yellow-900/40 text-yellow-400'
  return 'bg-green-900/40 text-green-400'
})

// --- Data fetch ---
async function fetchMonitorStatus() {
  try {
    const r = await api.get('/api/v1/monitor/status')
    const d = r.data
    monitorData.value = d
    const uptimeSec = parseInt(d.redis?.uptime_seconds || '0')
    const h = Math.floor(uptimeSec / 3600)
    const m = Math.floor((uptimeSec % 3600) / 60)
    goStatus.value = {
      online: true,
      uptime: uptimeSec > 86400 ? `${Math.floor(uptimeSec / 86400)}天${h % 24}时` : `${h}时${m}分`,
      memory: d.redis?.used_memory_human || '--',
      redis: d.redis?.connected ?? false,
    }
  } catch { goStatus.value.online = false }
}

async function fetchMT5Status() {
  try {
    const [serverR, statusR] = await Promise.all([
      api.get('/api/v1/mt5-server/status').catch(() => ({ data: {} })),
      api.get('/api/v1/mt5/connection/status').catch(() => ({ data: {} })),
    ])
    const srv = serverR.data || {}
    const s = statusR.data || {}
    mt5System.value = { online: srv.online ?? (Object.keys(srv).length > 0) ?? !s.error, uptime: srv.uptime || srv.run_time || '--', memory: srv.memory || srv.mem_usage || '--', cpu: srv.cpu || srv.cpu_usage || '--', instances: srv.instances ?? srv.bridge_count ?? '--', connected: s.connected ?? false }
  } catch { mt5System.value = { online: false } }
}

async function fetchStats() {
  try {
    const r = await api.get('/api/v1/ws/stats')
    stats.value.wsConnections = r.data?.connections?.total ?? 0
  } catch {}
}

async function fetchUserFinancials() {
  usersLoading.value = true
  try {
    const [usersRes, dashRes] = await Promise.all([
      api.get('/api/v1/users'),
      api.get('/api/v1/accounts/dashboard/aggregated').catch(() => ({ data: { summary: {}, accounts: [] } })),
    ])
    const users = Array.isArray(usersRes.data) ? usersRes.data : usersRes.data?.users || []
    stats.value.totalUsers = users.length

    // Build users map (traders only)
    const uMap = {}
    for (const u of users) {
      const roleName = u.rbac_roles?.[0]?.role_name || u.role || '--'
      const roleCode = u.rbac_roles?.[0]?.role_code || u.role || ''
      if (roleCode !== 'trader' && roleName !== '交易员') continue
      uMap[u.user_id] = { user_id: u.user_id, username: u.username, role: roleName }
    }
    usersMap.value = uMap

    const d = dashRes.data
    if (d.summary) {
      stats.value.activeAccounts = d.summary.account_count ?? 0
      stats.value.totalPositions = d.summary.position_count ?? 0
    }
    const accs = []
    if (d.accounts) accs.push(...d.accounts)
    if (d.failed_accounts) {
      for (const fa of d.failed_accounts) accs.push({ ...fa, _error: fa.error || '获取失败' })
    }
    allAccounts.value = accs
    rebuildUserFinancials()
  } catch (e) { console.error('fetchUserFinancials:', e) }
  finally { usersLoading.value = false }
}

async function fetchProxyAccounts() {
  try {
    const r = await api.get('/api/v1/accounts', { params: { all: 'true' } })
    const all = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    proxyAccounts.value = all.filter(a => a.is_active && a.proxy_config)
    // Enrich with IPIPGO order data
    try {
      const ipipR = await api.get('/api/v1/users/ipipgo-orders')
      const orders = ipipR.data?.orders || []
      for (const acc of proxyAccounts.value) {
        if (!acc.proxy_config?.region) continue
        const region = acc.proxy_config.region.replace(/[-\s]/g, '').toLowerCase()
        const order = orders.find(o => {
          const country = (o.country || '').replace(/[-\s]/g, '').toLowerCase()
          return country === region || country.includes(region) || region.includes(country)
        })
        if (order) {
          acc.proxy_config.allocated_at = acc.proxy_config.allocated_at || order.allocated_at
          acc.proxy_config.expires_at = acc.proxy_config.expires_at || order.expires_at
          acc.proxy_config.ip_status = order.ip_status
        }
      }
    } catch {}
  } catch {}
}

async function fetchHedgingPairs() {
  try {
    const r = await api.get('/api/v1/hedging/pairs')
    hedgingPairs.value = Array.isArray(r.data) ? r.data : []
  } catch { hedgingPairs.value = [] }
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([fetchMonitorStatus(), fetchStats(), fetchUserFinancials(), fetchMT5Status(), fetchProxyAccounts(), fetchHedgingPairs()])
  lastUpdate.value = dayjs().format('HH:mm:ss')
  refreshing.value = false
}

// --- Helpers ---
function getBal(acc, field) {
  if (acc.balance?.[field] != null) return parseFloat(acc.balance[field])
  if (acc[field] != null) return parseFloat(acc[field])
  return null
}

function accOwnerName(acc) {
  const uid = acc.user_id
  return usersMap.value[uid]?.username || ''
}

function accRiskLevel(acc) {
  const r = getBal(acc, 'risk_ratio')
  if (r == null) return 'ok'
  if (r > 80) return 'danger'
  if (r > 50) return 'warning'
  return 'ok'
}

function accBorderClass(acc) {
  if (acc._error) return 'border-red-800/50'
  const level = accRiskLevel(acc)
  if (level === 'danger') return 'border-red-800/50'
  if (level === 'warning') return 'border-yellow-800/50'
  return 'border-border-primary'
}

function platformName(id) { return { 1: 'Binance', 2: 'Bybit', 3: 'IC Markets' }[id] || 'Unknown' }
function isMT5Online(c) { return c.online || c.connection_status === 'connected' }

function fmtNum(v) {
  if (v == null) return '--'
  return parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function pnlStr(v) {
  if (v == null || isNaN(v)) return '--'
  const n = parseFloat(v)
  return (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function pnlClass(v) { return v == null ? '' : v >= 0 ? 'text-success' : 'text-danger' }
function riskClass(v) {
  if (v == null) return 'text-text-tertiary'
  if (v < 50) return 'text-success'
  if (v < 80) return 'text-warning'
  return 'text-danger font-bold'
}
function roleBadgeClass(role) {
  return { '超级管理员': 'bg-red-900/40 text-red-300', '系统管理员': 'bg-orange-900/40 text-orange-300', '安全管理员': 'bg-yellow-900/40 text-yellow-300', '交易员': 'bg-blue-900/40 text-blue-300', '观察员': 'bg-gray-700 text-gray-300' }[role] || 'bg-dark-200 text-text-secondary'
}
function sslDaysClass(d) { return d == null ? 'text-text-tertiary' : d <= 7 ? 'text-red-400 font-bold' : d <= 30 ? 'text-yellow-400 font-bold' : 'text-green-400' }
function sslStatusText(s) { return { healthy: '正常', warning: '即将过期', critical: '紧急', expired: '已过期', error: '错误' }[s] || '--' }
function sslStatusBadge(s) { return { healthy: 'bg-green-900/40 text-green-400', warning: 'bg-yellow-900/40 text-yellow-400', critical: 'bg-red-900/40 text-red-400', expired: 'bg-red-900/60 text-red-300' }[s] || 'bg-dark-300 text-text-tertiary' }
function feishuText(s) { return { healthy: '正常', disabled: '已禁用', not_configured: '未配置' }[s] || '--' }
function proxyIPStatus(acc) { return acc.proxy_config?.expires_at && new Date(acc.proxy_config.expires_at) < new Date() ? 'expired' : 'active' }
function proxyDaysLeft(acc) { const exp = acc.proxy_config?.expires_at; return exp ? Math.ceil((new Date(exp) - new Date()) / 86400000) : '--' }
function proxyDaysClass(d) { return d === '--' ? 'text-text-secondary' : d <= 7 ? 'text-red-400 font-bold' : d <= 30 ? 'text-yellow-400' : 'text-text-secondary' }
function proxyStatusClass(s) { return { active: 'bg-green-900/40 text-green-400', expired: 'bg-red-900/40 text-red-400' }[s] || 'bg-dark-300 text-text-tertiary' }
function proxyStatusText(s) { return { active: '正常', expired: '已过期', pending: '待生效' }[s] || s || '未知' }

// --- Lifecycle ---
onMounted(async () => {
  await refreshAll()
  wsConnect()
})
onUnmounted(() => {
  wsDisconnect()
  clearInterval(fallbackTimer)
})
</script>
