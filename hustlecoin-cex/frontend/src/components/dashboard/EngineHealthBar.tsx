import { useState, useEffect, useCallback, useRef } from 'react'
import { Badge } from '@/components/ui/badge'
import { getEngineHealth, restartWorker, startWorker, stopWorker, type EngineHealth } from '@/api/engine'
import { useBalanceStore } from '@/stores/balanceStore'
import { useToastStore } from '@/components/ui/toast'
import {
  Activity, AlertTriangle, ChevronDown, ChevronUp,
  Heart, Server, Zap, Gauge, Clock, Wallet,
} from 'lucide-react'
import { HoldingsSummary } from './HoldingsSummary'

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
  const [showHoldings, setShowHoldings] = useState(false)
  const [error, setError] = useState(false)
  const balanceSummary = useBalanceStore((s) => s.summary)  // 顶栏「合约 未平/累计」移到此
  const addToast = useToastStore((s) => s.addToast)
  const abortRef = useRef<AbortController | null>(null)

  // [第三梯队] AbortController:慢网下若上一次 health 仍在途,先撤销再发新请求,避免请求堆叠抢带宽
  const fetchHealth = useCallback(() => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    getEngineHealth(ctrl.signal)
      .then((d) => { setHealth(d); setError(false) })
      .catch((e: { code?: string; name?: string }) => {
        if (e?.code === 'ERR_CANCELED' || e?.name === 'CanceledError') return  // 主动取消不算错误
        setError(true)
      })
  }, [])

  // 单 worker 操作: scope=sub:N → id=N;操作后延迟回读(reconcile ~10s 生效)
  const workerAction = useCallback(async (scope: string, kind: 'restart' | 'stop' | 'start') => {
    const id = parseInt(scope.replace('sub:', ''), 10)
    if (isNaN(id)) return
    const fn = kind === 'restart' ? restartWorker : kind === 'stop' ? stopWorker : startWorker
    try {
      const r = await fn(id)
      addToast(r.message || '已发送', 'success')
      setTimeout(fetchHealth, 2000)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      addToast(err.response?.data?.detail || '操作失败', 'error')
    }
  }, [addToast, fetchHealth])

  useEffect(() => {
    fetchHealth()
    const timer = setInterval(fetchHealth, 15000)
    return () => { clearInterval(timer); abortRef.current?.abort() }
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
  // API错误改「近5分钟实时」口径:total_errors 是进程级单调累计(只增不减),陈旧错误会常驻误报。
  // 仅当该账户最近一次错误发生在 300s 内才计入,既反映真实近期故障,又不被历史累计污染。
  const ERR_FRESH_SEC = 300
  const totalMetrics = Object.values(health.api_metrics).reduce(
    (acc, m) => ({
      calls: acc.calls + m.total_calls,
      errors: acc.errors + (m.last_error_ago_sec != null && m.last_error_ago_sec < ERR_FRESH_SEC ? m.total_errors : 0),
      rate_limited: acc.rate_limited + m.rate_limited,
    }),
    { calls: 0, errors: 0, rate_limited: 0 },
  )

  return (
    <div className="border-b border-border bg-card/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2 text-xs hover:bg-accent/50 transition-colors"
      >
        <div className="flex items-center gap-1.5">
          <Icon className={`h-3.5 w-3.5 ${health.status === 'HEALTHY' ? 'text-positive' : health.status === 'DEGRADED' ? 'text-yellow-500' : 'text-negative'}`} />
          <Badge variant={cfg.variant}>{cfg.label}</Badge>
        </div>

        <span className="hidden sm:inline text-muted-foreground">|</span>

        {/* engine mode (挂单中/已停止) + uptime */}
        <div className="flex items-center gap-1.5">
          <Badge variant={isRunning ? 'success' : 'secondary'}>{isRunning ? '挂单中' : '已停止'}</Badge>
          {isRunning && health.uptime_sec != null && (
            <span className="flex items-center gap-0.5 text-muted-foreground">
              <Clock className="h-3 w-3" />{fmtUptime(health.uptime_sec)}
            </span>
          )}
        </div>

        <span className="hidden sm:inline text-muted-foreground">|</span>

        {/* UID 借币权重 gauge(1500/次,限额 180000) */}
        <div className="flex items-center gap-1" title={`UID 借币权重 ${usedWeight}/${weightLimit} (1分钟单UID限额,借币 1500/次)${health.weight_age_sec != null ? ` · ${health.weight_age_sec}s前` : ''}`}>
          <Gauge className={`h-3 w-3 ${weightColor}`} />
          <span className={weightColor}>UID {usedWeight}/{weightLimit}</span>
          <span className="hidden sm:inline-block w-12 h-1.5 rounded-full bg-muted overflow-hidden align-middle">
            <span className={`block h-full ${weightBar}`} style={{ width: `${weightPct}%` }} />
          </span>
        </div>

        <span className="hidden sm:inline text-muted-foreground">|</span>

        <div className="flex items-center gap-1">
          <Server className="h-3 w-3 text-muted-foreground" />
          <span>{runningWorkers.length} Worker</span>
          {staleWorkers.length > 0 && (
            <Badge variant="warning" className="ml-1">{staleWorkers.length} 超时</Badge>
          )}
        </div>

        <span className="hidden sm:inline text-muted-foreground">|</span>

        {/* 单UID建仓速率 = 最近60s内最忙子账户实际成功借币次数/60(实时实际速率,非理论上限) */}
        <div className="flex items-center gap-1" title="单UID建仓速率 = 最近60秒内最忙子账户实际成功借币次数 ÷ 60(req/s);反映引擎此刻真实建仓节奏,无近期借币则为0">
          <Gauge className="h-3 w-3 text-primary" />
          <span>单UID建仓速率 <span className="text-primary font-mono">{(health.single_borrow_rate ?? 0).toFixed(1)}</span>/s</span>
        </div>

        <span className="hidden sm:inline text-muted-foreground">|</span>

        <div className="flex items-center gap-1">
          <Zap className="h-3 w-3 text-muted-foreground" />
          <span>{health.spread_count} 币对</span>
        </div>

        {totalMetrics.errors > 0 && (
          <>
            <span className="hidden sm:inline text-muted-foreground">|</span>
            <span className="text-negative">API错误: {totalMetrics.errors}</span>
          </>
        )}

        {/* 持仓 + 合约 — 移到状态条最右侧 */}
        <span className="hidden sm:inline text-muted-foreground">|</span>
        <div className="flex items-center gap-1">
          <Activity className="h-3 w-3 text-muted-foreground" />
          <span>{health.open_positions} 持仓</span>
          {health.stuck_positions.length > 0 && (
            <Badge variant="destructive" className="ml-1">{health.stuck_positions.length} 卡住</Badge>
          )}
        </div>

        <span className="hidden sm:inline text-muted-foreground">|</span>
        <div className="flex items-center gap-1" title="合约: 未平仓 / 累计持仓数">
          <span>合约 <span className="text-primary">{balanceSummary.positionCount}</span>/<span className="text-muted-foreground">{balanceSummary.totalContracts}</span></span>
        </div>

        <button
          onClick={(e) => { e.stopPropagation(); setShowHoldings(true) }}
          title="持币汇总 — 各子账户已借币种,逐笔单独还币"
          className="ml-auto flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-muted-foreground hover:text-foreground hover:bg-accent/60"
        >
          <Wallet className="h-3 w-3" />持币汇总
        </button>
        <div>
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border/50 px-4 py-3 space-y-3">
          {/* Workers */}
          {health.workers.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-muted-foreground mb-1.5">Workers</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 lg:grid-cols-4">
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
                      <button
                        onClick={(e) => { e.stopPropagation(); workerAction(w.scope, 'restart') }}
                        className="px-1.5 py-0.5 rounded border border-border text-[10px] text-primary hover:bg-accent/50"
                        title="重启该 worker(卡死/超时时单独重启,不影响其他)"
                      >重启</button>
                      {w.status === 'RUNNING' ? (
                        <button
                          onClick={(e) => { e.stopPropagation(); workerAction(w.scope, 'stop') }}
                          className="px-1.5 py-0.5 rounded border border-border text-[10px] text-negative hover:bg-accent/50"
                          title="停用该子账户(有在场持仓则保留至平仓)"
                        >停</button>
                      ) : (
                        <button
                          onClick={(e) => { e.stopPropagation(); workerAction(w.scope, 'start') }}
                          className="px-1.5 py-0.5 rounded border border-border text-[10px] text-positive hover:bg-accent/50"
                          title="启用该子账户"
                        >启</button>
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
      {showHoldings && <HoldingsSummary onClose={() => setShowHoldings(false)} />}
    </div>
  )
}
