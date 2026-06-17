import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardOverview, type DashboardOverview, type EngineUserStatus } from '@/api/admin'
import { useAutoRefresh } from '@/hooks/useAutoRefresh'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { formatNumber } from '@/lib/utils'
import { AdminMarquee } from '@/components/AdminMarquee'
import {
  Server, Database, Activity, Users, TrendingUp, Globe, Shield,
  RefreshCw, Clock, Wifi, WifiOff, Bell, BellOff, Bot, Zap,
  Radio, MessageSquare, Cpu, Heart, AlertTriangle,
} from 'lucide-react'

export function DashboardPage() {
  const [data, setData] = useState<DashboardOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const d = await getDashboardOverview()
      setData(d)
      setLastUpdate(new Date())
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useAutoRefresh(fetchData, 10000)

  const manualRefresh = () => {
    setRefreshing(true)
    fetchData()
  }

  if (loading) return <div className="text-muted-foreground p-8 text-center">Loading...</div>
  if (!data) return <div className="text-negative p-8 text-center">Failed to load dashboard</div>

  const pnlValue = parseFloat(data.today.pnl)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold">总控面板</h1>
        <div className="flex flex-wrap items-center gap-2">
          {lastUpdate && (Date.now() - lastUpdate.getTime()) > 30000 && (
            <Badge variant="destructive" className="text-[10px]">数据可能已过时</Badge>
          )}
          {lastUpdate && (
            <span className="text-xs text-muted-foreground">
              <Clock className="mr-1 inline h-3 w-3" />
              {lastUpdate.toLocaleTimeString('zh-CN')} 更新
            </span>
          )}
          <button
            onClick={manualRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs transition-colors hover:bg-accent disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
      </div>

      {/* 后台内置跑马灯:API 文档变动等告警(轮询近 24h marquee 广播) */}
      <AdminMarquee />

      {/* Row 1: Core Business (3 columns) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Server className="h-4 w-4 text-primary" />
              Python 后端
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="PID" value={String(data.server.pid)} />
              <InfoRow label="运行时长" value={data.server.python_uptime} />
              <InfoRow label="内存占用" value={`${data.server.memory_mb} MB`} />
              <InfoRow label="CPU" value={`${data.server.cpu_percent}%`} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="h-4 w-4 text-primary" />
              套利引擎
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="运行引擎" value={`${data.engines.running} / ${data.engines.total}`}
                color={data.engines.running > 0 ? 'text-positive' : 'text-negative'} />
              <InfoRow label="活跃用户" value={String(data.engine_users.filter(u => u.status === 'RUNNING').length)} />
              <InfoRow label="总 Worker" value={String(data.engine_users.reduce((s, u) => s + u.worker_count, 0))} />
              <InfoRow label="在线持仓" value={String(data.positions.open)} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <TrendingUp className="h-4 w-4 text-primary" />
              实时统计
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="用户总数" value={`${data.users.active} / ${data.users.total}`} />
              <InfoRow label="持仓总额" value={`${formatNumber(data.positions.total_usdt)} USDT`} />
              <InfoRow label="今日 PnL"
                value={`${pnlValue >= 0 ? '+' : ''}${formatNumber(data.today.pnl)} USDT`}
                color={pnlValue >= 0 ? 'text-positive' : 'text-negative'} />
              <InfoRow label="今日平仓" value={`${data.today.closed_count} 笔`} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Row 2: Infrastructure Services (4 columns) */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {/* Redis */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Database className="h-4 w-4 text-primary" />
              Redis
              <Badge variant={data.server.redis.connected ? 'success' : 'destructive'} className="ml-auto">
                {data.server.redis.connected ? '已连接' : '断开'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="版本" value={data.server.redis.version} />
              <InfoRow label="内存" value={data.server.redis.used_memory_human} />
              <InfoRow label="客户端" value={String(data.server.redis.connected_clients)} />
              <InfoRow label="Keys" value={String(data.server.redis.keys)} />
            </div>
          </CardContent>
        </Card>

        {/* Rust Engine */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Cpu className="h-4 w-4 text-orange-500" />
              Rust 引擎
              <Badge variant={data.rust_engine.status === 'running' ? 'success' : data.rust_engine.status === 'idle' ? 'warning' : 'destructive'} className="ml-auto">
                {data.rust_engine.status === 'running' ? '运行中' : data.rust_engine.status === 'idle' ? '空闲' : data.rust_engine.status === 'stopped' ? '已停止' : '未知'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="服务" value="cex-engine" />
              <InfoRow label="Spread 对" value={`${data.rust_engine.spread_pairs} 个`}
                color={data.rust_engine.spread_pairs > 0 ? 'text-positive' : 'text-muted-foreground'} />
              <InfoRow label="数据通道" value={data.rust_engine.channel_active ? '活跃' : '断开'}
                color={data.rust_engine.channel_active ? 'text-positive' : 'text-negative'} />
            </div>
          </CardContent>
        </Card>

        {/* Feishu */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              {data.feishu.connected
                ? <Bell className="h-4 w-4 text-positive" />
                : <BellOff className="h-4 w-4 text-muted-foreground" />}
              飞书通知
              <div className="ml-auto flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${data.feishu.connected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
                <span className={`text-xs font-medium ${data.feishu.connected ? 'text-green-500' : 'text-red-500'}`}>
                  {data.feishu.connected ? '已连接' : '未连接'}
                </span>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              {data.feishu.connected && data.feishu.token_expires_at && (
                <InfoRow label="Token 到期" value={new Date(data.feishu.token_expires_at).toLocaleString('zh-CN')} />
              )}
              {!data.feishu.connected && data.feishu.error && (
                <p className="text-xs text-negative">{data.feishu.error}</p>
              )}
              <InfoRow label="Webhook" value={`${data.feishu.webhooks} 个`}
                color={data.feishu.webhooks > 0 ? 'text-positive' : 'text-muted-foreground'} />
              <InfoRow label="用户配置" value={`${data.feishu.count} 个`} />
            </div>
          </CardContent>
        </Card>

        {/* AiCoin API */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Zap className="h-4 w-4 text-yellow-500" />
              AiCoin API
              <Badge variant={data.aicoin.connected ? 'success' : data.aicoin.api_key_set ? 'destructive' : 'secondary'} className="ml-auto">
                {data.aicoin.connected ? '已连接' : data.aicoin.api_key_set ? '连接失败' : '未配置'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="API Key" value={data.aicoin.api_key_set ? '已配置' : '未配置'}
                color={data.aicoin.api_key_set ? 'text-positive' : 'text-negative'} />
              <InfoRow label="连接状态" value={data.aicoin.connected ? '正常' : data.aicoin.error ? '异常' : '未测试'}
                color={data.aicoin.connected ? 'text-positive' : 'text-negative'} />
              {data.aicoin.error && (
                <p className="text-xs text-negative truncate" title={data.aicoin.error}>{data.aicoin.error}</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Row 3: AI Chat + WebSocket (2 columns) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* AI Chat Status */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Bot className="h-4 w-4 text-purple-500" />
              AI 客服
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              {Object.entries(data.ai_chat).map(([site, info]) => (
                <div key={site} className="space-y-2 text-sm">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="font-medium">{site === 'coin' ? '用户端' : '管理端'}</span>
                    <Badge variant={info.enabled ? 'success' : 'secondary'} className="ml-auto">
                      {info.enabled ? 'ON' : 'OFF'}
                    </Badge>
                  </div>
                  <InfoRow label="Provider" value={info.provider || '-'} />
                  <InfoRow label="模型" value={info.model ? info.model.split('/').pop()! : '-'} />
                  <InfoRow label="今日消息" value={String(info.today_messages)} />
                  <InfoRow label="总对话数" value={String(info.total_conversations)} />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* WebSocket Monitor */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Radio className="h-4 w-4 text-blue-500" />
              WebSocket 监控
              <Badge variant={data.websocket.connections > 0 ? 'success' : 'secondary'} className="ml-auto">
                {data.websocket.connections} 连接
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <InfoRow label="活跃连接" value={String(data.websocket.connections)}
                color={data.websocket.connections > 0 ? 'text-positive' : 'text-muted-foreground'} />
              <div className="border-t pt-2 mt-2">
                <p className="text-xs text-muted-foreground mb-1.5">数据流状态</p>
                <div className="space-y-1.5">
                  {data.websocket.streamers.map((s) => (
                    <div key={s.name} className="flex items-center justify-between text-xs">
                      <span>{s.name}</span>
                      <Badge variant={s.status === 'active' ? 'success' : s.status === 'error' ? 'destructive' : 'secondary'}>
                        {s.status === 'active' ? '活跃' : s.status === 'error' ? '异常' : '空闲'}
                        {s.count > 0 && ` (${s.count})`}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Row 4: SSL + Proxy */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* SSL Certs */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Shield className="h-4 w-4 text-primary" />
              SSL 证书
              {data.cert_warnings.length > 0 && (
                <Badge variant="warning" className="ml-auto">{data.cert_warnings.length} 即将到期</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.ssl_certs.length === 0 ? (
              <p className="text-xs text-muted-foreground">暂无证书</p>
            ) : (
              <div className="space-y-1.5">
                {data.ssl_certs.map((c) => (
                  <div key={c.id} className="flex items-center justify-between text-xs">
                    <span className="truncate mr-2">{c.domain}</span>
                    {c.days_left != null ? (
                      <Badge variant={c.days_left <= 7 ? 'destructive' : c.days_left <= 30 ? 'warning' : 'success'}>
                        {c.days_left}天
                      </Badge>
                    ) : (
                      <Badge variant="secondary">未知</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Proxy */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Globe className="h-4 w-4 text-primary" />
              代理池状态
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-4 text-sm">
              <div className="flex items-center gap-2">
                <Wifi className="h-4 w-4 text-positive" />
                <span>正常: <strong>{data.proxies.active}</strong></span>
              </div>
              <div className="flex items-center gap-2">
                <WifiOff className="h-4 w-4 text-negative" />
                <span>异常: <strong className={data.proxies.error > 0 ? 'text-negative' : ''}>{data.proxies.error}</strong></span>
              </div>
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-muted-foreground" />
                <span>总数: <strong>{data.proxies.total}</strong></span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Row 5: Engine Health */}
      {data.engine_health && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              {data.engine_health.status === 'HEALTHY'
                ? <Heart className="h-4 w-4 text-positive" />
                : <AlertTriangle className="h-4 w-4 text-yellow-500" />}
              引擎健康
              <Badge
                variant={data.engine_health.status === 'HEALTHY' ? 'success' : data.engine_health.status === 'DEGRADED' ? 'warning' : 'destructive'}
                className="ml-auto"
              >
                {data.engine_health.status === 'HEALTHY' ? '正常' : data.engine_health.status === 'DEGRADED' ? '异常' : '故障'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Stale Workers */}
            {data.engine_health.stale_workers.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-yellow-500 mb-1">Worker 心跳超时</p>
                <div className="space-y-1">
                  {data.engine_health.stale_workers.map((w) => (
                    <div key={w.scope} className="flex items-center gap-2 text-xs">
                      <Badge variant="warning">{w.scope}</Badge>
                      <span className="text-muted-foreground">超时 {Math.floor(w.stale_seconds / 60)} 分钟</span>
                      <span className="text-muted-foreground">上次: {w.last_heartbeat}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Stuck Positions */}
            {data.engine_health.stuck_positions.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-negative mb-1">卡住的持仓 ({data.engine_health.stuck_positions.length})</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="pb-1 pr-3">ID</th>
                        <th className="pb-1 pr-3">币种</th>
                        <th className="pb-1 pr-3">状态</th>
                        <th className="pb-1 pr-3 text-right">卡住时间</th>
                        <th className="pb-1 pr-3">账户</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.engine_health.stuck_positions.map((p) => (
                        <tr key={p.id} className="border-b border-border/30">
                          <td className="py-1 pr-3">
                            <Link to={`/admin/history?tab=logs&position_id=${p.id}`} className="text-primary hover:underline" title="查看该持仓执行流水">#{p.id}</Link>
                          </td>
                          <td className="py-1 pr-3 font-medium">{p.symbol}</td>
                          <td className="py-1 pr-3"><Badge variant="destructive">{p.status}</Badge></td>
                          <td className="py-1 pr-3 text-right">{p.stuck_minutes} 分钟</td>
                          <td className="py-1 pr-3">#{p.sub_account_id}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* API Metrics */}
            {Object.keys(data.engine_health.api_metrics).length > 0 && (
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-1">API 指标</p>
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                  {Object.entries(data.engine_health.api_metrics).map(([key, m]) => (
                    <div key={key} className="rounded-md border px-2.5 py-1.5 text-xs">
                      <span className="font-medium">账户 #{key}</span>
                      <div className="mt-1 space-y-0.5 text-muted-foreground">
                        <div>调用: {m.total_calls}</div>
                        <div className={m.total_errors > 0 ? 'text-negative' : ''}>
                          错误: {m.total_errors} ({m.error_rate}%)
                        </div>
                        {m.rate_limited > 0 && <div className="text-yellow-500">限流: {m.rate_limited}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.engine_health.stuck_positions.length === 0 && data.engine_health.stale_workers.length === 0 && Object.keys(data.engine_health.api_metrics).length === 0 && (
              <p className="text-sm text-muted-foreground">所有系统正常运行</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Row 6: Engine Users Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Users className="h-4 w-4 text-primary" />
            引擎用户汇总
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.engine_users.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无用户引擎数据</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="pb-2 pr-4">用户</th>
                    <th className="pb-2 pr-4">状态</th>
                    <th className="pb-2 pr-4 text-right">Worker</th>
                    <th className="pb-2 pr-4 text-right">持仓数</th>
                    <th className="pb-2 pr-4 text-right">累计 PnL</th>
                    <th className="pb-2 text-right">最近交易</th>
                  </tr>
                </thead>
                <tbody>
                  {data.engine_users.map((u: EngineUserStatus) => (
                    <EngineUserRow key={u.user_id} user={u} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Row 6: Mini Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MiniStat label="今日平仓" value={`${data.today.closed_count} 笔`} />
        <MiniStat label="今日 PnL" value={`${formatNumber(data.today.pnl)} USDT`}
          color={pnlValue >= 0 ? 'text-positive' : 'text-negative'} />
        <MiniStat label="总资金费" value={`${formatNumber(data.positions.total_funding)} USDT`} />
        <MiniStat label="总利息" value={`${formatNumber(data.positions.total_interest)} USDT`} color="text-negative" />
      </div>
    </div>
  )
}

function InfoRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={color || ''}>{value}</span>
    </div>
  )
}

function EngineUserRow({ user }: { user: EngineUserStatus }) {
  const pnl = parseFloat(user.total_pnl)
  return (
    <tr className="border-b border-border/50 last:border-0">
      <td className="py-2 pr-4 font-medium">{user.username}</td>
      <td className="py-2 pr-4">
        <Badge variant={user.status === 'RUNNING' ? 'success' : 'secondary'}>
          {user.status === 'RUNNING' ? '运行中' : '已停止'}
        </Badge>
      </td>
      <td className="py-2 pr-4 text-right">{user.worker_count}</td>
      <td className="py-2 pr-4 text-right">{user.open_positions}</td>
      <td className={`py-2 pr-4 text-right ${pnl >= 0 ? 'text-positive' : 'text-negative'}`}>
        {formatNumber(user.total_pnl)}
      </td>
      <td className="py-2 text-right text-xs text-muted-foreground">
        {user.last_trade_at ? new Date(user.last_trade_at).toLocaleString('zh-CN') : '-'}
      </td>
    </tr>
  )
}

function MiniStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`mt-1 text-lg font-bold ${color || ''}`}>{value}</p>
      </CardContent>
    </Card>
  )
}
