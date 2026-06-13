import { useState, useEffect, useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { getEngineHealth, type EngineHealth } from '@/api/engine'
import { useBalanceStore } from '@/stores/balanceStore'
import {
  Activity, AlertTriangle, ChevronDown, ChevronUp,
  Heart, Server, Zap, Gauge, Clock,
} from 'lucide-react'

const STATUS_CONFIG = {
  HEALTHY: { label: '正常', variant: 'success' as const, icon: Heart },
  DEGRADED: { label: '异常', variant: 'warning' as const, icon: AlertTriangle },
  UNHEALTHY: { label: '故障', variant: 'destructive' as const, icon: AlertTriangle },
}

function fmtUptime(sec: number): string {
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (d > 0) return `${d}d${h}h`
  if (h > 0) return `${h}h${m}m`
  return `${m}m${String(s).padStart(2, '0')}s`
}

export function EngineHealthBar() {
  const [health, setHealth] = useState<EngineHealth | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState(false)
  const balanceSummary = useBalanceStore((s) => s.summary)  // 顶栏「合约 未平/累计」移到此

  const fetchHealth = useCallback(() => {
    getEngineHealth()
      .then((d) => { setHealth(d); setError(false) })
      .catch(() => setError(true))
  }, [])

  useEffect(() => {
    fetchHealth()
    const timer = setInterval(fetchHealth, 15000)
    return () => clearInterval(timer)
  }, [fetchHealth])

  if (error && !health) return null
  if (!health) return null

  const cfg = STATUS_CONFIG[health.status] || STATUS_CONFIG.UNHEALTHY
  const Icon = cfg.icon
  const staleWorkers = health.workers.filter(w => w.heartbeat_stale)
  const runningWorkers = health.workers.filter(w => w.status === 'RUNNING')
  const isRunning = health.engine_status === 'RUNNING'
  // 顶栏「UID」= 借币 UID 权重(1500/次,限额 180000)—— 借币的真实硬约束
  const usedWeight = health.uid_used_1m ?? 0
  const weightLimit = health.uid_limit || 180000
  const weightPct = Math.min(100, Math.round((usedWeight / weightLimit) * 100))
  const weightColor = weightPct >= 85 ? 'text-negative' : weightPct >= 60 ? 'text-yellow-500' : 'text-positive'
  const weightBar = weightPct >= 85 ? 'bg-negative' : weightPct >= 60 ? 'bg-yellow-500' : 'bg-positive'
  const totalMetrics = Object.values(health.api_metrics).reduce(
    (acc, m) => ({
      calls: acc.calls + m.total_calls,
      errors: acc.errors + m.total_errors,
      rate_limited: acc.rate_limited + m.rate_limited,
    }),
    { calls: 0, errors: 0, rate_limited: 0 },
  )

  return (
    <div className="border-b border-border bg-card/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-2 text-xs hover:bg-accent/50 transition-colors"
      >
        <div className="flex items-center gap-1.5">
          <Icon className={`h-3.5 w-3.5 ${health.status === 'HEALTHY' ? 'text-positive' : health.status === 'DEGRADED' ? 'text-yellow-500' : 'text-negative'}`} />
          <Badge variant={cfg.variant}>{cfg.label}</Badge>
        </div>

        <span className="text-muted-foreground">|</span>

        {/* engine mode (挂单中/已停止) + uptime */}
        <div className="flex items-center gap-1.5">
          <Badge variant={isRunning ? 'success' : 'secondary'}>{isRunning ? '挂单中' : '已停止'}</Badge>
          {isRunning && health.uptime_sec != null && (
            <span className="flex items-center gap-0.5 text-muted-foreground">
              <Clock className="h-3 w-3" />{fmtUptime(health.uptime_sec)}
            </span>
          )}
        </div>

        <span className="text-muted-foreground">|</span>

        {/* UID 借币权重 gauge(1500/次,限额 180000) */}
        <div className="flex items-center gap-1" title={`UID 借币权重 ${usedWeight}/${weightLimit} (1分钟单UID限额,借币 1500/次)${health.weight_age_sec != null ? ` · ${health.weight_age_sec}s前` : ''}`}>
          <Gauge className={`h-3 w-3 ${weightColor}`} />
          <span className={weightColor}>UID {usedWeight}/{weightLimit}</span>
          <span className="hidden sm:inline-block w-12 h-1.5 rounded-full bg-muted overflow-hidden align-middle">
            <span className={`block h-full ${weightBar}`} style={{ width: `${weightPct}%` }} />
          </span>
        </div>

        <span className="text-muted-foreground">|</span>

        <div className="flex items-center gap-1">
          <Server className="h-3 w-3 text-muted-foreground" />
          <span>{runningWorkers.length} Worker</span>
          {staleWorkers.length > 0 && (
            <Badge variant="warning" className="ml-1">{staleWorkers.length} 超时</Badge>
          )}
        </div>

        <span className="text-muted-foreground">|</span>

        {/* 聚合借速 = min( Σ 各账户配速[每账户≤2/s 单UID硬顶], 共享IP预算上限 ) */}
        <div className="flex items-center gap-1" title="可持续聚合借速 = min( Σ 各启用子账户配速[每账户封顶 2/s 单UID硬顶], 共享IP预算上限 ) (req/s)">
          <Gauge className="h-3 w-3 text-primary" />
          <span>聚合借速 <span className="text-primary font-mono">{(health.agg_borrow_rate ?? 0).toFixed(1)}</span>/s</span>
        </div>

        <span className="text-muted-foreground">|</span>

        <div className="flex items-center gap-1">
          <Zap className="h-3 w-3 text-muted-foreground" />
          <span>{health.spread_count} 币对</span>
        </div>

        {totalMetrics.errors > 0 && (
          <>
            <span className="text-muted-foreground">|</span>
            <span className="text-negative">API错误: {totalMetrics.errors}</span>
          </>
        )}

        {/* 持仓 + 合约 — 移到状态条最右侧 */}
        <span className="text-muted-foreground">|</span>
        <div className="flex items-center gap-1">
          <Activity className="h-3 w-3 text-muted-foreground" />
          <span>{health.open_positions} 持仓</span>
          {health.stuck_positions.length > 0 && (
            <Badge variant="destructive" className="ml-1">{health.stuck_positions.length} 卡住</Badge>
          )}
        </div>

        <span className="text-muted-foreground">|</span>
        <div className="flex items-center gap-1" title="合约: 未平仓 / 累计持仓数">
          <span>合约 <span className="text-primary">{balanceSummary.positionCount}</span>/<span className="text-muted-foreground">{balanceSummary.totalContracts}</span></span>
        </div>

        <div className="ml-auto">
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border/50 px-4 py-3 space-y-3">
          {/* Workers */}
          {health.workers.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground mb-1.5">Workers</p>
              <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                {health.workers.map(w => (
                  <div key={w.scope} className="flex items-center justify-between rounded-md border px-2.5 py-1.5 text-xs">
                    <span className="font-medium">{w.scope.replace('sub:', '#')}</span>
                    <div className="flex items-center gap-1.5">
                      <Badge variant={w.status === 'RUNNING' ? 'success' : w.status === 'ERROR' ? 'destructive' : 'secondary'}>
                        {w.status === 'RUNNING' ? '运行' : w.status === 'ERROR' ? '错误' : '停止'}
                      </Badge>
                      {w.heartbeat_stale && (
                        <Badge variant="warning">超时</Badge>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stuck Positions */}
          {health.stuck_positions.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-negative mb-1.5">卡住的持仓</p>
              <div className="space-y-1">
                {health.stuck_positions.map(p => (
                  <div key={p.id} className="flex items-center gap-2 text-xs text-negative">
                    <span className="font-medium">{p.symbol}</span>
                    <span>#{p.id}</span>
                    <Badge variant="destructive">{p.status}</Badge>
                    <span>{p.stuck_minutes}分钟</span>
                    {p.error_message && (
                      <span className="truncate text-muted-foreground" title={p.error_message}>{p.error_message}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* API Metrics */}
          {totalMetrics.calls > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground mb-1.5">API 指标</p>
              <div className="flex flex-wrap gap-4 text-xs">
                <span>总调用: {totalMetrics.calls}</span>
                <span className={totalMetrics.errors > 0 ? 'text-negative' : ''}>
                  错误: {totalMetrics.errors}
                </span>
                {totalMetrics.rate_limited > 0 && (
                  <span className="text-yellow-500">限流: {totalMetrics.rate_limited}</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
