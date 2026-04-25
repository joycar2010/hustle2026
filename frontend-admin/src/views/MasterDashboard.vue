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
          <SparklineChart v-if="sparklineData.length > 1" :data="sparklineData" color="#22d3ee" width="80px" height="20px" />
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
        <DataStaleBadge :lastUpdateAt="lastUpdateTs" :thresholdMs="35000" />
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

      <!-- Fund summary cards with embedded visualizations -->
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">总资产 (USDT)</div>
          <div class="flex items-center justify-between">
            <div class="font-mono font-bold text-lg text-text-primary">{{ fmtNum(totals.total_assets) }}</div>
            <MiniDonut v-if="platformDist.length" :segments="platformDist" size="48px" />
          </div>
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">可用资产</div>
          <div class="font-mono font-bold text-lg text-text-secondary mb-1.5">{{ fmtNum(totals.available_assets) }}</div>
          <div class="h-1.5 bg-dark-300 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all duration-500" :style="{ width: availableRate + '%' }" :class="availableRate > 50 ? 'bg-green-500' : availableRate > 25 ? 'bg-yellow-500' : 'bg-red-500'"></div>
          </div>
          <div class="text-[10px] text-text-tertiary mt-0.5 text-right">{{ availableRate.toFixed(0) }}%</div>
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">净资产</div>
          <div class="font-mono font-bold text-lg text-text-secondary">{{ fmtNum(totals.net_assets) }}</div>
          <SparklineChart v-if="sparklineData.length > 1" :data="sparklineData" color="#22d3ee" width="100%" height="28px" />
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">当日盈亏</div>
          <div class="font-mono font-bold text-lg" :class="pnlClass(totals.daily_pnl)">
            {{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}
          </div>
          <MiniBarChart v-if="pnlHistory.length > 1" :data="pnlHistory.map(d => d.pnl)" :labels="pnlHistory.map(d => d.date)" width="100%" height="32px" />
        </div>
        <div class="bg-dark-100 rounded-xl p-4 border border-border-primary">
          <div class="text-xs text-text-tertiary mb-1">持仓 / 用户</div>
          <div class="font-mono font-bold text-lg text-primary mb-1">{{ stats.totalPositions ?? 0 }} / {{ stats.totalUsers ?? 0 }}</div>
          <div class="flex items-center gap-2 text-[10px]">
            <div class="flex-1">
              <div class="flex justify-between text-text-tertiary"><span>Long</span><span class="font-mono">{{ positionSummary.long }}</span></div>
              <div class="h-1 bg-dark-300 rounded-full mt-0.5"><div class="h-full bg-green-500 rounded-full" :style="{ width: positionSummary.longPct + '%' }"></div></div>
            </div>
            <div class="flex-1">
              <div class="flex justify-between text-text-tertiary"><span>Short</span><span class="font-mono">{{ positionSummary.short }}</span></div>
              <div class="h-1 bg-dark-300 rounded-full mt-0.5"><div class="h-full bg-red-500 rounded-full" :style="{ width: positionSummary.shortPct + '%' }"></div></div>
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
                <td class="px-3 py-2.5 text-right font-mono font-semibold relative">
                  <div class="absolute inset-0 flex items-center"><div class="h-full bg-primary/10 rounded" :style="{ width: assetBarWidth(u.total_assets) + '%' }"></div></div>
                  <span class="relative">{{ fmtNum(u.total_assets) }}</span>
                </td>
                <td class="px-3 py-2.5 text-right font-mono text-text-secondary">{{ fmtNum(u.net_assets) }}</td>
                <td class="px-3 py-2.5 text-right font-mono font-semibold" :class="pnlClass(u.daily_pnl)">
                  {{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}
                </td>
                <td class="px-5 py-2.5 text-right"><span class="px-1.5 py-0.5 rounded text-xs font-bold" :class="riskBadgeClass(u.risk_rate)">{{ u.risk_rate != null ? u.risk_rate.toFixed(1) + '%' : '--' }}</span></td>
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
                  {{ acc.is_mt5_account ? ('MT5·' + platformName(acc.platform_id)) : platformName(acc.platform_id) }}
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
          <div class="flex items-start gap-2">
            <div class="flex-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <div class="flex justify-between"><span class="text-text-tertiary">净资产</span><span class="font-mono text-text-primary">{{ fmtNum(getBal(acc, 'net_assets')) }}</span></div>
              <div class="flex justify-between"><span class="text-text-tertiary">可用</span><span class="font-mono text-text-secondary">{{ fmtNum(getBal(acc, 'available_balance')) }}</span></div>
              <div class="flex justify-between"><span class="text-text-tertiary">浮盈亏</span><span class="font-mono" :class="pnlClass(getBal(acc, 'unrealized_pnl'))">{{ pnlStr(getBal(acc, 'unrealized_pnl')) }}</span></div>
              <div class="flex justify-between">
                <span class="text-text-tertiary">保证金率</span>
                <span class="font-mono" :class="riskClass(getBal(acc, 'risk_ratio'))">{{ getBal(acc, 'risk_ratio') != null ? getBal(acc, 'risk_ratio').toFixed(1) + '%' : '--' }}</span>
              </div>
            </div>
            <RiskGauge v-if="getBal(acc, 'risk_ratio') != null" :value="Math.min(getBal(acc, 'risk_ratio'), 100)" width="72px" height="44px" />
          </div>
          <!-- Position count -->
          <div class="mt-2 pt-1.5 border-t border-border-secondary flex justify-between text-xs">
            <span class="text-text-tertiary">持仓</span>
            <span class="font-mono font-bold" :class="(acc.positions || []).length ? 'text-primary' : 'text-text-tertiary'">{{ (acc.positions || []).length }} 笔</span>
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
          <HedgeBalance
            :valueA="getHedgePosition(pair, 'a')"
            :valueB="getHedgePosition(pair, 'b')"
            :labelA="pair.platform_a?.platform_name || 'CEX'"
            :labelB="pair.platform_b?.platform_name || 'MT5'"
            class="mb-2"
          />
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>CEX</span><span class="font-mono text-text-secondary">{{ pair.symbol_a?.symbol || '--' }}</span></div>
            <div class="flex justify-between"><span>MT5</span><span class="font-mono text-text-secondary">{{ pair.symbol_b?.symbol || '--' }}</span></div>
            <div class="flex justify-between"><span>转换因子</span><span class="font-mono text-primary font-bold">{{ pair.conversion_factor || '--' }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Layer 3: Infrastructure ===== -->
    <div class="space-y-2">
      <h2 class="text-sm font-semibold text-text-tertiary uppercase tracking-wider px-1">基础设施</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">

        <!-- Card A: 服务集群 (API + MT5 Bridge) -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="goStatus.online && mt5System.online ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-semibold">服务集群</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded-full" :class="goStatus.online && mt5System.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
              {{ goStatus.online && mt5System.online ? '全部在线' : '部分异常' }}
            </span>
          </div>
          <div class="space-y-2">
            <div class="flex items-center gap-2 text-xs">
              <div :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', goStatus.online ? 'bg-green-500' : 'bg-red-500']"></div>
              <span class="text-text-tertiary w-16">Python API</span>
              <span class="font-mono text-text-secondary flex-1 text-right">:8000</span>
              <span class="font-mono text-text-tertiary text-[10px] w-16 text-right">{{ goStatus.uptime || '--' }}</span>
            </div>
            <div class="flex items-center gap-2 text-xs">
              <div :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', goStatus.online ? 'bg-green-500' : 'bg-red-500']"></div>
              <span class="text-text-tertiary w-16">Go API</span>
              <span class="font-mono text-text-secondary flex-1 text-right">:8080</span>
              <span class="font-mono text-text-tertiary text-[10px] w-16 text-right">{{ goStatus.memory || '--' }}</span>
            </div>
            <div class="border-t border-border-secondary my-1"></div>
            <div class="flex items-center gap-2 text-xs">
              <div :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', mt5System.online ? 'bg-green-500' : 'bg-red-500']"></div>
              <span class="text-text-tertiary w-16">MT5 Bridge</span>
              <span class="font-mono text-text-secondary flex-1 text-right">{{ mt5System.instances ?? '--' }} 实例</span>
              <span class="font-mono text-text-tertiary text-[10px] w-16 text-right">{{ mt5System.uptime || '--' }}</span>
            </div>
            <div class="flex items-center gap-2 text-xs">
              <div class="w-1.5 h-1.5 flex-shrink-0"></div>
              <span class="text-text-tertiary w-16">内存</span>
              <span class="font-mono text-text-secondary flex-1 text-right">API {{ goStatus.memory || '--' }} / MT5 {{ mt5System.memory || '--' }}</span>
            </div>
          </div>
        </div>

        <!-- Card B: 数据与服务 (Redis/DB Pool/WS + 后端服务状态) -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="monitorData.redis?.connected ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-semibold">数据与服务</span>
            <span class="text-[10px]" :class="monitorData.redis?.connected ? 'text-green-400' : 'text-red-400'">
              {{ monitorData.redis?.connected ? '正常' : '异常' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>Redis</span><span class="font-mono text-text-secondary">v{{ monitorData.redis?.version || '--' }} / {{ monitorData.redis?.used_memory_human || '--' }}</span></div>
            <div class="flex justify-between"><span>Redis 客户端</span><span class="font-mono text-text-secondary">{{ monitorData.redis?.connected_clients || '--' }}</span></div>
            <div class="flex justify-between"><span>WS 连接</span><span class="font-mono text-primary font-bold">{{ stats.wsConnections ?? 0 }}</span></div>
          </div>
          <div class="border-t border-border-secondary mt-2 pt-2">
            <div class="flex items-center justify-between text-xs mb-1.5">
              <span class="text-text-tertiary">数据库连接池</span>
              <span class="font-mono" :class="dbPoolUsagePct > 80 ? 'text-red-400' : dbPoolUsagePct > 60 ? 'text-yellow-400' : 'text-green-400'">
                {{ dbPool.active }}/{{ dbPool.max }}
              </span>
            </div>
            <div class="h-1.5 bg-dark-300 rounded-full overflow-hidden mb-1">
              <div class="h-full rounded-full transition-all duration-500"
                :style="{ width: dbPoolUsagePct + '%' }"
                :class="dbPoolUsagePct > 80 ? 'bg-red-500' : dbPoolUsagePct > 60 ? 'bg-yellow-500' : 'bg-green-500'">
              </div>
            </div>
            <div class="flex justify-between text-[10px] text-text-tertiary">
              <span>活跃 {{ dbPool.active }} · 空闲 {{ dbPool.idle }}</span>
              <span>{{ dbPoolUsagePct.toFixed(0) }}%</span>
            </div>
          </div>
          <div class="border-t border-border-secondary mt-2 pt-2 text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>持仓监控</span><span class="text-green-400">运行中</span></div>
            <div class="flex justify-between"><span>飞书通知</span>
              <span :class="monitorData.feishu?.status === 'healthy' ? 'text-green-400' : monitorData.feishu?.status === 'disabled' ? 'text-yellow-400' : 'text-text-tertiary'">
                {{ feishuText(monitorData.feishu?.status) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Card C: Agent & Bridges (独立 + 心跳线) -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="mt5Infra.reachable ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-semibold">Agent & Bridges</span>
            <span class="text-[10px]" :class="mt5Infra.reachable ? 'text-green-400' : 'text-red-400'">
              {{ mt5Infra.reachable ? (mt5Infra.status === 'ok' ? '正常' : '降级') : '不可达' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between">
              <span>Agent 运行</span>
              <span class="font-mono text-text-secondary">{{ fmtUptime(mt5Infra.uptime_seconds) }}</span>
            </div>
            <div class="flex justify-between">
              <span>Bridges</span>
              <span :class="mt5Infra.bridges?.alive === mt5Infra.bridges?.total ? 'text-green-400' : 'text-red-400'" class="font-mono">
                {{ mt5Infra.bridges?.alive || 0 }}/{{ mt5Infra.bridges?.total || 0 }} 活跃
              </span>
            </div>
            <div v-if="mt5Infra.bridges?.detail" class="grid grid-cols-2 gap-x-3 gap-y-0.5 mt-1">
              <div v-for="b in mt5Infra.bridges.detail" :key="b.service" class="flex items-center justify-between text-[10px]">
                <span class="truncate text-text-tertiary" :title="b.service">:{{ b.port }}</span>
                <div :class="['w-1.5 h-1.5 rounded-full', b.state === 'running' || b.state === 'paused' ? 'bg-green-500' : 'bg-red-500']"></div>
              </div>
            </div>
          </div>
          <div class="mt-2 pt-2 border-t border-border-secondary">
            <div class="flex items-center justify-between mb-1">
              <span class="text-[10px] text-text-tertiary">心跳</span>
              <span class="text-[10px] font-mono" :class="agentHbColor">{{ agentHeartbeats.length ? agentHeartbeats[agentHeartbeats.length-1].ms + 'ms' : '--' }}</span>
            </div>
            <div class="flex items-end gap-px h-6">
              <div v-for="(hb, i) in agentHeartbeats.slice(-40)" :key="i"
                class="flex-1 rounded-t transition-all"
                :style="{ height: Math.min(hb.ms / 30, 100) + '%' }"
                :class="hb.ms > 5000 ? 'bg-red-500' : hb.ms > 2000 ? 'bg-yellow-500' : 'bg-green-500'"
                :title="hb.ms + 'ms'">
              </div>
            </div>
          </div>
        </div>

        <!-- Card D: MT5 客户端 (独立 + 心跳线) -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="mt5ClientsOnline > 0 ? 'border-green-800/30' : 'border-red-800/30'">
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-semibold">MT5 客户端</span>
            <span class="text-[10px]" :class="mt5ClientsOnline > 0 ? 'text-green-400' : 'text-red-400'">
              {{ mt5ClientsOnline }}/{{ mt5ClientsTotal }} 在线
            </span>
          </div>
          <div v-if="monitorData.mt5_clients?.length" class="space-y-1">
            <div v-for="cl in monitorData.mt5_clients" :key="cl.mt5_login" class="flex items-center justify-between text-[10px]">
              <div class="flex items-center gap-1.5 truncate">
                <div :class="['w-1.5 h-1.5 rounded-full flex-shrink-0', isMT5Online(cl) ? 'bg-green-500' : 'bg-red-500']"></div>
                <span class="text-text-secondary truncate">{{ cl.client_name }}</span>
                <span v-if="cl.is_system_service" class="px-0.5 text-purple-400 flex-shrink-0">SYS</span>
              </div>
              <span class="text-text-tertiary font-mono ml-1">{{ cl.mt5_login }}</span>
            </div>
          </div>
          <div v-else class="text-xs text-text-tertiary text-center py-2">暂无客户端</div>
          <div class="mt-2 pt-2 border-t border-border-secondary">
            <div class="flex items-center justify-between mb-1">
              <span class="text-[10px] text-text-tertiary">心跳</span>
              <span class="text-[10px] font-mono" :class="mt5HbColor">{{ mt5Heartbeats.length ? mt5Heartbeats[mt5Heartbeats.length-1].ms + 'ms' : '--' }}</span>
            </div>
            <div class="flex items-end gap-px h-6">
              <div v-for="(hb, i) in mt5Heartbeats.slice(-40)" :key="i"
                class="flex-1 rounded-t transition-all"
                :style="{ height: Math.min(hb.ms / 30, 100) + '%' }"
                :class="hb.ms > 5000 ? 'bg-red-500' : hb.ms > 2000 ? 'bg-yellow-500' : 'bg-green-500'"
                :title="hb.ms + 'ms'">
              </div>
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

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from '@/composables/useWebSocket.js'
import { useBroadcastChannel } from '@/composables/useBroadcastChannel.js'
import api from '@/services/api.js'
import dayjs from 'dayjs'
import SparklineChart from '@/components/SparklineChart.vue'
import MiniDonut from '@/components/MiniDonut.vue'
import RiskGauge from '@/components/RiskGauge.vue'
import MiniBarChart from '@/components/MiniBarChart.vue'
import HedgeBalance from '@/components/HedgeBalance.vue'
import DataStaleBadge from '@/components/DataStaleBadge.vue'

// --- WebSocket ---
const { connected: wsConnected, lastMessage, connect: wsConnect, disconnect: wsDisconnect } = useWebSocket()
let fallbackTimer = null

// --- State ---
const refreshing = ref(false)
const usersLoading = ref(true)
const lastUpdate = ref('--')

const goStatus = ref({ online: false, uptime: '', memory: '', redis: false })
const dbPool = ref({ active: 0, idle: 0, max: 0 })
const mt5System = ref({ online: false })
const mt5Infra = ref({ reachable: false, status: null, uptime_seconds: 0, instances: { running: 0, total: 0 }, bridges: { alive: 0, total: 0, detail: [] } })
const stats = ref({ wsConnections: 0, totalUsers: 0, activeAccounts: 0, totalPositions: 0 })
const allAccounts = ref([])
const userFinancials = ref([])
const monitorData = ref({ redis: null, ssl_certificate: [], feishu: null, mt5_clients: [] })
const proxyAccounts = ref([])
const hedgingPairs = ref([])
const usersMap = ref({})
const sparklineData = ref([])
const pnlHistory = ref([])
const platformDist = ref([])
const lastUpdateTs = ref(0)
const agentHeartbeats = ref([])
const mt5Heartbeats = ref([])
let lastAgentPingAt = 0
let lastMt5PingAt = 0

const { broadcast: bcBroadcast, init: bcInit } = useBroadcastChannel()

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
  lastUpdateTs.value = Date.now()
}

function rebuildUserFinancials() {
  const map = {}
  for (const [uid, u] of Object.entries(usersMap.value)) {
    map[uid] = { ...u, account_count: 0, total_assets: 0, available_assets: 0, net_assets: 0, daily_pnl: 0, risk_rate: null }
  }
  for (const acc of allAccounts.value.filter(a => a.is_active !== false)) {
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

const dbPoolUsagePct = computed(() => {
  return dbPool.value.max > 0 ? (dbPool.value.active / dbPool.value.max) * 100 : 0
})

const agentHbColor = computed(() => {
  if (!agentHeartbeats.value.length) return 'text-text-tertiary'
  const last = agentHeartbeats.value[agentHeartbeats.value.length - 1].ms
  return last > 5000 ? 'text-red-400' : last > 2000 ? 'text-yellow-400' : 'text-green-400'
})

const mt5HbColor = computed(() => {
  if (!mt5Heartbeats.value.length) return 'text-text-tertiary'
  const last = mt5Heartbeats.value[mt5Heartbeats.value.length - 1].ms
  return last > 5000 ? 'text-red-400' : last > 2000 ? 'text-yellow-400' : 'text-green-400'
})

const availableRate = computed(() => {
  const total = totals.value.total_assets
  const avail = totals.value.available_assets
  return total > 0 ? (avail / total) * 100 : 0
})

const positionSummary = computed(() => {
  let long = 0, short = 0
  for (const acc of allAccounts.value) {
    for (const p of (acc.positions || [])) {
      if (p.type === 0 || p.side === 'long' || p.side === 'LONG') long++
      else short++
    }
  }
  const total = long + short || 1
  return { long, short, longPct: (long / total * 100).toFixed(0), shortPct: (short / total * 100).toFixed(0) }
})

const sortedAccounts = computed(() => {
  return [...allAccounts.value].filter(a => a.is_active !== false).sort((a, b) => {
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
  const maxRisk = Math.max(...allAccounts.value.filter(a => a.is_active !== false).map(a => getBal(a, 'risk_ratio') || 0), 0)
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
    const [monitorR, sysR] = await Promise.all([
      api.get('/api/v1/monitor/status'),
      api.get('/api/v1/system/status').catch(() => ({ data: {} })),
    ])
    const d = monitorR.data
    monitorData.value = d
    const uptimeSec = parseInt(d.redis?.uptime_seconds || '0')
    const h = Math.floor(uptimeSec / 3600)
    const m = Math.floor((uptimeSec % 3600) / 60)
    goStatus.value = {
      online: true,
      uptime: sysR.data?.uptime || (uptimeSec > 86400 ? `${Math.floor(uptimeSec / 86400)}天${h % 24}时` : `${h}时${m}分`),
      memory: d.redis?.used_memory_human || '--',
      redis: d.redis?.connected ?? false,
    }
    if (sysR.data?.dbPool) {
      dbPool.value = sysR.data.dbPool
    }
    // Use system/status MT5 field to supplement mt5System
    if (sysR.data?.mt5 !== undefined) {
      mt5System.value = {
        ...mt5System.value,
        online: sysR.data.mt5,
        uptime: sysR.data.uptime || mt5System.value.uptime,
      }
    }
  } catch { goStatus.value.online = false }
}

async function fetchMT5Status() {
  try {
    const r = await api.get('/api/v1/mt5-infra/status').catch(() => ({ data: {} }))
    const d = r.data || {}
    mt5System.value = {
      online: d.reachable ?? false,
      uptime: fmtUptime(d.uptime_seconds) || '--',
      memory: '--',
      instances: d.bridges?.total ?? '--',
      connected: d.reachable ?? false,
    }
  } catch { mt5System.value = { online: false } }
}

async function fetchMT5Infra() {
  try {
    const r = await api.get('/api/v1/mt5-infra/status')
    mt5Infra.value = r.data || mt5Infra.value
  } catch { mt5Infra.value = { ...mt5Infra.value, reachable: false } }
}

function fmtUptime(sec) {
  if (!sec || sec < 1) return '--'
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60)
  if (d > 0) return d + 'd' + h + 'h'
  if (h > 0) return h + 'h' + m + 'm'
  return m + 'm'
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
      api.get('/api/v1/accounts/dashboard/aggregated?include_inactive=true').catch(() => ({ data: { summary: {}, accounts: [] } })),
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

async function fetchSparkline() {
  try {
    const r = await api.get('/api/v1/accounts/dashboard/sparkline?hours=24&interval=1h')
    sparklineData.value = (r.data?.data || []).map(d => d.equity)
  } catch {}
}

async function fetchPnlHistory() {
  try {
    const r = await api.get('/api/v1/accounts/dashboard/pnl-history?days=7')
    pnlHistory.value = r.data?.data || []
  } catch {}
}

async function fetchPlatformDist() {
  try {
    const r = await api.get('/api/v1/accounts/dashboard/platform-distribution')
    const COLORS = ['#3b82f6', '#a855f7', '#f59e0b', '#10b981', '#ef4444', '#6366f1']
    platformDist.value = (r.data?.data || []).filter(d => d.total_equity > 0).map((d, i) => ({
      name: d.platform_name, value: d.total_equity, color: COLORS[i % COLORS.length]
    }))
  } catch {}
}

function getHedgePosition(pair, side) {
  for (const acc of allAccounts.value) {
    for (const p of (acc.positions || [])) {
      const sym = p.symbol || ''
      if (side === 'a' && acc.platform_id === (pair.platform_a_id || pair.platform_a?.platform_id) && sym.includes('XAU')) return p.volume || 0
      if (side === 'b' && acc.platform_id === (pair.platform_b_id || pair.platform_b?.platform_id) && sym.includes('XAU')) return p.volume || 0
    }
  }
  return 0
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([fetchMonitorStatus(), fetchStats(), fetchUserFinancials(), fetchMT5Status(), fetchMT5Infra(), fetchProxyAccounts(), fetchHedgingPairs(), fetchSparkline(), fetchPnlHistory(), fetchPlatformDist()])
  lastUpdate.value = dayjs().format('HH:mm:ss')
  lastUpdateTs.value = Date.now()

  // Sample heartbeats from infra status
  const now = Date.now()
  if (mt5Infra.value.reachable && lastAgentPingAt > 0) {
    const interval = now - lastAgentPingAt
    agentHeartbeats.value.push({ time: now, ms: interval })
    if (agentHeartbeats.value.length > 60) agentHeartbeats.value.shift()
  }
  lastAgentPingAt = now

  if (mt5ClientsOnline.value > 0 && lastMt5PingAt > 0) {
    const interval = now - lastMt5PingAt
    mt5Heartbeats.value.push({ time: now, ms: interval })
    if (mt5Heartbeats.value.length > 60) mt5Heartbeats.value.shift()
  }
  lastMt5PingAt = now

  refreshing.value = false
  bcBroadcast({ type: 'dashboard_refresh', ts: Date.now() })
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

function platformName(id) { return { 1: 'Binance', 2: 'Bybit', 3: 'IC Markets Global', 4: 'Gate.io', 5: 'OKX' }[id] || 'Unknown' }
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
function assetBarWidth(v) {
  const max = Math.max(...userFinancials.value.map(u => u.total_assets || 0), 1)
  return v > 0 ? (v / max * 100).toFixed(0) : 0
}

function riskBadgeClass(v) {
  if (v == null) return 'bg-dark-300 text-text-tertiary'
  if (v < 30) return 'bg-green-900/40 text-green-400'
  if (v < 60) return 'bg-yellow-900/40 text-yellow-400'
  if (v < 80) return 'bg-orange-900/40 text-orange-400'
  return 'bg-red-900/40 text-red-400'
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
  bcInit()
  await refreshAll()
  wsConnect()
})
onUnmounted(() => {
  wsDisconnect()
  clearInterval(fallbackTimer)
})
</script>
