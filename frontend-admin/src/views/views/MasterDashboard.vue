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

        <!-- Python 后端服务器 -->
        <div class="bg-dark-100 rounded-xl p-4 border" :class="goStatus.online ? 'border-green-800/50' : 'border-red-800/50'">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div :class="['w-2.5 h-2.5 rounded-full', goStatus.online ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
              <span class="text-sm font-semibold text-text-primary">后端 API 服务</span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded-full" :class="goStatus.online ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'">
              {{ goStatus.online ? '在线' : '离线' }}
            </span>
          </div>
          <div class="text-xs text-text-tertiary space-y-1">
            <div class="flex justify-between"><span>端口</span><span class="text-text-secondary font-mono">:8000</span></div>
            <div class="flex justify-between"><span>运行时长</span><span class="text-text-secondary font-mono">{{ goStatus.uptime || '--' }}</span></div>
            <div class="flex justify-between"><span>内存使用</span><span class="text-text-secondary font-mono">{{ goStatus.memory || '--' }}</span></div>
            <div class="flex justify-between"><span>Redis 连接</span>
              <span :class="goStatus.redis ? 'text-green-400' : 'text-red-400'">{{ goStatus.redis ? '正常' : '异常' }}</span>
            </div>
          </div>
        </div>

        <!-- MT5 桥接服务器 -->
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
            <div class="flex justify-between"><span>运行时长</span><span class="text-text-secondary font-mono">{{ mt5System.uptime || '--' }}</span></div>
            <div class="flex justify-between"><span>内存</span><span class="text-text-secondary font-mono">{{ mt5System.memory || '--' }}</span></div>
            <div class="flex justify-between"><span>CPU</span><span class="text-text-secondary font-mono">{{ mt5System.cpu || '--' }}</span></div>
            <div class="flex justify-between"><span>Bridge 实例</span><span class="text-text-secondary font-mono">{{ mt5System.instances ?? '--' }} 个</span></div>
            <div class="flex justify-between"><span>MT5 连接</span>
              <span :class="mt5System.connected ? 'text-green-400' : 'text-yellow-400'">{{ mt5System.connected ? '已连接' : '未连接' }}</span>
            </div>
            <div class="flex justify-between"><span>MT5 登录</span><span class="text-text-secondary font-mono">{{ mt5System.login || '--' }}</span></div>
            <div v-if="mt5System.balance != null" class="flex justify-between"><span>权益</span><span class="text-text-secondary font-mono">{{ mt5System.balance?.toFixed(2) }} UST</span></div>
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
              <span>API 服务</span>
              <span :class="goStatus.online ? 'text-green-400' : 'text-red-400'">{{ goStatus.online ? '运行中' : '异常' }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span>MT5 Bridge</span>
              <span :class="mt5System.online ? 'text-green-400' : 'text-red-400'">{{ mt5System.online ? '运行中' : '异常' }}</span>
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
              <span :class="monitorData.feishu?.status === 'healthy' ? 'text-green-400' : monitorData.feishu?.status === 'disabled' ? 'text-yellow-400' : 'text-text-tertiary'">
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
              <span class="font-medium text-text-primary truncate max-w-[60%]">{{ acc.account_name }}</span>
              <span v-if="acc.proxy_config" class="px-1.5 py-0.5 rounded" :class="proxyStatusClass(acc.proxy_config.ip_status || proxyIPStatus(acc))">
                {{ proxyStatusText(acc.proxy_config.ip_status || proxyIPStatus(acc)) }}
              </span>
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
              <div v-if="acc.proxy_config.allocated_at || acc.proxy_config.expires_at" class="border-t border-border-primary mt-1.5 pt-1.5 space-y-0.5">
                <div v-if="acc.proxy_config.allocated_at" class="flex justify-between">
                  <span>分配时间</span>
                  <span class="font-mono text-text-secondary">{{ acc.proxy_config.allocated_at }}</span>
                </div>
                <div v-if="acc.proxy_config.expires_at" class="flex justify-between">
                  <span>过期时间</span>
                  <span class="font-mono" :class="proxyDaysClass(proxyDaysLeft(acc))">
                    {{ acc.proxy_config.expires_at }}
                    <span class="text-text-tertiary font-normal"> ({{ proxyDaysLeft(acc) }}天)</span>
                  </span>
                </div>
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
            <div :class="['w-2.5 h-2.5 rounded-full', monitorData.mt5_clients?.some(c => isMT5Online(c)) ? 'bg-green-500 animate-pulse' : 'bg-red-500']"></div>
            <span class="text-sm font-semibold text-text-primary">MT5 客户端</span>
            <span class="text-xs text-text-tertiary">({{ monitorData.mt5_clients?.filter(c => isMT5Online(c)).length ?? 0 }}/{{ monitorData.mt5_clients?.length ?? 0 }} 在线)</span>
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
                <span :class="isMT5Online(c) ? 'text-green-400' : 'text-red-400'">{{ isMT5Online(c) ? '在线' : '离线' }}</span>
              </div>
            </div>
          </div>
          <div v-else class="text-xs text-text-tertiary text-center py-3">暂无 MT5 客户端数据</div>
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

      <!-- Desktop table -->
      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[800px]">
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
              <td colspan="8" class="text-center py-12 text-text-tertiary">加载中...</td>
            </tr>
            <tr v-else-if="!userFinancials.length">
              <td colspan="8" class="text-center py-12 text-text-tertiary">暂无数据</td>
            </tr>
            <tr v-for="u in userFinancials" :key="u.user_id"
              class="border-b border-border-secondary hover:bg-dark-50 transition-colors">
              <td class="px-5 py-3 font-medium text-text-primary whitespace-nowrap">{{ u.username }}</td>
              <td class="px-4 py-3 whitespace-nowrap">
                <span class="px-2 py-0.5 rounded text-xs" :class="roleBadgeClass(u.role)">{{ u.role || '--' }}</span>
              </td>
              <td class="px-4 py-3 text-right text-text-secondary whitespace-nowrap">{{ u.account_count ?? '--' }}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold whitespace-nowrap">{{ fmtNum(u.total_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary whitespace-nowrap">{{ fmtNum(u.available_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary whitespace-nowrap">{{ fmtNum(u.net_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold whitespace-nowrap" :class="pnlClass(u.daily_pnl)">
                {{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}
              </td>
              <td class="px-5 py-3 text-right whitespace-nowrap">
                <span :class="riskClass(u.risk_rate)">{{ u.risk_rate != null ? u.risk_rate.toFixed(2) + '%' : '--' }}</span>
              </td>
            </tr>
          </tbody>
          <tfoot v-if="userFinancials.length" class="border-t-2 border-border-primary">
            <tr class="bg-dark-50 text-sm font-semibold">
              <td class="px-5 py-3 text-text-secondary whitespace-nowrap" colspan="3">合计</td>
              <td class="px-4 py-3 text-right font-mono whitespace-nowrap">{{ fmtNum(totals.total_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary whitespace-nowrap">{{ fmtNum(totals.available_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono text-text-secondary whitespace-nowrap">{{ fmtNum(totals.net_assets) }}</td>
              <td class="px-4 py-3 text-right font-mono whitespace-nowrap" :class="pnlClass(totals.daily_pnl)">
                {{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}
              </td>
              <td class="px-5 py-3"></td>
            </tr>
          </tfoot>
        </table>
      </div>

      <!-- Mobile cards -->
      <div class="md:hidden space-y-3 p-3">
        <div v-if="usersLoading" class="text-center py-8 text-text-tertiary text-sm">加载中...</div>
        <div v-else-if="!userFinancials.length" class="text-center py-8 text-text-tertiary text-sm">暂无数据</div>
        <div v-for="u in userFinancials" :key="u.user_id"
          class="bg-dark-200 rounded-xl p-3 space-y-2 border border-border-secondary">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="font-bold text-sm">{{ u.username }}</span>
              <span class="px-1.5 py-0.5 rounded text-xs" :class="roleBadgeClass(u.role)">{{ u.role || '--' }}</span>
            </div>
            <span class="text-xs text-text-tertiary">{{ u.account_count ?? '--' }} 账户</span>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="bg-dark-300 rounded p-2">
              <div class="text-text-tertiary mb-0.5">总资产</div>
              <div class="font-mono font-bold">{{ fmtNum(u.total_assets) }}</div>
            </div>
            <div class="bg-dark-300 rounded p-2">
              <div class="text-text-tertiary mb-0.5">可用资产</div>
              <div class="font-mono">{{ fmtNum(u.available_assets) }}</div>
            </div>
            <div class="bg-dark-300 rounded p-2">
              <div class="text-text-tertiary mb-0.5">净资产</div>
              <div class="font-mono">{{ fmtNum(u.net_assets) }}</div>
            </div>
            <div class="bg-dark-300 rounded p-2">
              <div class="text-text-tertiary mb-0.5">当日盈亏</div>
              <div class="font-mono font-bold" :class="pnlClass(u.daily_pnl)">
                {{ u.daily_pnl != null ? (u.daily_pnl >= 0 ? '+' : '') + fmtNum(u.daily_pnl) : '--' }}
              </div>
            </div>
          </div>
          <div class="flex justify-between text-xs pt-1 border-t border-border-primary">
            <span class="text-text-tertiary">风险率</span>
            <span :class="riskClass(u.risk_rate)">{{ u.risk_rate != null ? u.risk_rate.toFixed(2) + '%' : '--' }}</span>
          </div>
        </div>
        <!-- Mobile total -->
        <div v-if="userFinancials.length" class="bg-dark-50 rounded-xl p-3 border border-primary/30">
          <div class="text-xs text-text-tertiary mb-2 font-semibold">合计</div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div><span class="text-text-tertiary">总资产: </span><span class="font-mono font-bold">{{ fmtNum(totals.total_assets) }}</span></div>
            <div><span class="text-text-tertiary">净资产: </span><span class="font-mono">{{ fmtNum(totals.net_assets) }}</span></div>
            <div><span class="text-text-tertiary">可用: </span><span class="font-mono">{{ fmtNum(totals.available_assets) }}</span></div>
            <div><span class="text-text-tertiary">盈亏: </span><span class="font-mono" :class="pnlClass(totals.daily_pnl)">{{ totals.daily_pnl >= 0 ? '+' : '' }}{{ fmtNum(totals.daily_pnl) }}</span></div>
          </div>
        </div>
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
const ipipgoOrders  = ref([])

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

    // 后端 API 服务状态：请求成功即在线
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
  } catch {
    goStatus.value.online = false
  }
}

async function fetchMT5Status() {
  try {
    const [serverR, statusR, infoR] = await Promise.all([
      api.get('/api/v1/mt5-server/status').catch(() => ({ data: {} })),
      api.get('/api/v1/mt5/connection/status').catch(() => ({ data: {} })),
      api.get('/api/v1/mt5/account/info').catch(() => ({ data: {} })),
    ])
    const srv = serverR.data || {}
    const s = statusR.data || {}
    const info = infoR.data || {}
    mt5System.value = {
      online:    srv.online ?? !s.error,
      uptime:    srv.uptime || '--',
      memory:    srv.memory || '--',
      cpu:       srv.cpu || '--',
      instances: srv.instances ?? '--',
      login:     String(s.account ?? info.login ?? '--'),
      server:    s.server ?? info.server ?? '--',
      connected: s.connected ?? false,
      balance:   info.equity ?? info.balance ?? s.balance ?? null,
    }
  } catch {
    mt5System.value = { online: false, uptime: '--', memory: '--', cpu: '--', instances: 0, login: '--', server: '--', connected: false }
  }
}

async function fetchStats() {
  try {
    // /api/v1/ws/stats returns {connections: {total: N}, service, timestamp}
    const r = await api.get('/api/v1/ws/stats')
    stats.value.wsConnections = r.data?.connections?.total ?? r.data?.ws_connections ?? 0
  } catch {}
}

async function fetchUserFinancials() {
  usersLoading.value = true
  try {
    // 并行获取用户列表 + 聚合面板（admin可见全部账户余额）
    const [usersRes, dashRes] = await Promise.all([
      api.get('/api/v1/users'),
      api.get('/api/v1/accounts/dashboard/aggregated').catch(() => ({ data: { summary: {}, accounts: [] } })),
    ])
    const users = Array.isArray(usersRes.data) ? usersRes.data : usersRes.data?.users || []
    const dashAccounts = dashRes.data?.accounts || []
    const summary = dashRes.data?.summary || {}
    stats.value.totalUsers = users.length
    stats.value.activeAccounts = summary.account_count || dashAccounts.length

    // Build per-user map — 只显示交易员角色
    const userMap = {}
    for (const u of users) {
      const role = u.rbac_roles?.[0]?.role_code || u.rbac_roles?.[0]?.role_name || u.role || ''
      const roleName = u.rbac_roles?.[0]?.role_name || u.role || '--'
      // 只保留交易员（trader / 交易员）
      if (role !== 'trader' && roleName !== '交易员') continue
      userMap[u.user_id] = {
        user_id: u.user_id,
        username: u.username,
        role: roleName,
        account_count: 0,
        total_assets: 0,
        available_assets: 0,
        net_assets: 0,
        daily_pnl: 0,
        risk_rate: null,
      }
    }

    // Aggregate per-account balance data into per-user rows
    for (const da of dashAccounts) {
      const uid = da.user_id
      if (uid && userMap[uid]) {
        const b = da.balance || {}
        userMap[uid].account_count++
        userMap[uid].total_assets     += b.total_assets || 0
        userMap[uid].available_assets += b.available_balance || 0
        userMap[uid].net_assets       += b.net_assets || 0
        userMap[uid].daily_pnl        += da.daily_pnl || b.daily_pnl || 0
        if (b.risk_ratio != null) userMap[uid].risk_rate = b.risk_ratio
      }
    }

    userFinancials.value = Object.values(userMap)
  } catch (e) {
    console.error('fetchUserFinancials error:', e)
  } finally {
    usersLoading.value = false
  }
}

async function fetchProxyAccounts() {
  try {
    const r = await api.get('/api/v1/accounts', { params: { all: 'true' } })
    const all = Array.isArray(r.data) ? r.data : (r.data?.accounts ?? [])
    proxyAccounts.value = all.filter(a => a.is_active && a.proxy_config)
    // Enrich proxy_config with live IPIPGO data in background
    fetchIPIPGOOrders()
  } catch {}
}

async function fetchIPIPGOOrders() {
  try {
    const r = await api.get('/api/v1/users/ipipgo-orders')
    ipipgoOrders.value = r.data?.orders || []
    // Auto-merge IPIPGO order data into proxy_config for matching accounts
    for (const acc of proxyAccounts.value) {
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
      }
    }
  } catch {}
}

function proxyIPStatus(acc) {
  const exp = acc.proxy_config?.expires_at
  if (!exp) return 'active'
  return new Date(exp) < new Date() ? 'expired' : 'active'
}

function proxyDaysLeft(acc) {
  const exp = acc.proxy_config?.expires_at
  if (!exp) return '--'
  const diff = Math.ceil((new Date(exp) - new Date()) / 86400000)
  return diff
}

function proxyDaysClass(days) {
  if (days === '--' || days == null) return 'text-text-secondary'
  if (days <= 7) return 'text-red-400 font-bold'
  if (days <= 30) return 'text-yellow-400'
  return 'text-text-secondary'
}

function isMT5Online(c) {
  return c.online || c.connection_status === 'connected'
}

function proxyStatusClass(status) {
  return {
    active:    'bg-green-900/40 text-green-400',
    expired:   'bg-red-900/40 text-red-400',
    pending:   'bg-yellow-900/40 text-yellow-400',
    cancelled: 'bg-dark-300 text-text-tertiary',
  }[status] || 'bg-dark-300 text-text-tertiary'
}

function proxyStatusText(status) {
  return { active: '正常', expired: '已过期', pending: '待生效', cancelled: '已取消' }[status] || status || '未知'
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
