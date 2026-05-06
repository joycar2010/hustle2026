import { useState, useEffect, useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { getEngineHealth, type EngineHealth } from '@/api/engine'
import {
  Activity, AlertTriangle, ChevronDown, ChevronUp,
  Heart, Server, Zap,
} from 'lucide-react'

const STATUS_CONFIG = {
  HEALTHY: { label: '正常', variant: 'success' as const, icon: Heart },
  DEGRADED: { label: '异常', variant: 'warning' as const, icon: AlertTriangle },
  UNHEALTHY: { label: '故障', variant: 'destructive' as const, icon: AlertTriangle },
}

export function EngineHealthBar() {
  const [health, setHealth] = useState<EngineHealth | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState(false)

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

        <div className="flex items-center gap-1">
          <Server className="h-3 w-3 text-muted-foreground" />
          <span>{runningWorkers.length} Worker</span>
          {staleWorkers.length > 0 && (
            <Badge variant="warning" className="ml-1">{staleWorkers.length} 超时</Badge>
          )}
        </div>

        <span className="text-muted-foreground">|</span>

        <div className="flex items-center gap-1">
          <Activity className="h-3 w-3 text-muted-foreground" />
          <span>{health.open_positions} 持仓</span>
          {health.stuck_positions.length > 0 && (
            <Badge variant="destructive" className="ml-1">{health.stuck_positions.length} 卡住</Badge>
          )}
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
