import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Clock3, Database, RefreshCw, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  type EarlyBorrowCandidate,
  type EarlyBorrowWarning,
  type EarlyBorrowCase,
  type EarlyBorrowStatus,
} from '@/api/earlyBorrow'
import { pushSymbol } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'
import {
  type EarlyBorrowLoadState,
  type EarlyBorrowResource,
} from '@/lib/earlyBorrowLoader'
import {
  getEarlyBorrowCache,
  isEarlyBorrowCacheFresh,
  loadEarlyBorrowCache,
  type EarlyBorrowCandidatesResponse,
  type EarlyBorrowCasesResponse,
  type EarlyBorrowResourceResult,
} from '@/lib/earlyBorrowCache'

function formatTime(value: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function pct(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '-' : `${(value * 100).toFixed(digits)}%`
}

function spread(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '-' : `${value.toFixed(3)}%`
}

function stateLabel(status: EarlyBorrowStatus | null, loadState: EarlyBorrowLoadState): string {
  if (!status && loadState === 'error') return '状态不可用'
  if (!status) return '加载中'
  switch (status.state) {
    case 'RUNNING': return '运行中'
    case 'WARMING_UP': return '采集预热'
    case 'WAITING_FOR_UNIVERSE': return '等待币种集合'
    case 'SERVICE_OFFLINE': return '服务未运行'
    case 'DISABLED': return '已禁用'
    case 'ERROR': return '采集异常'
    case 'STOPPED': return '已停止'
    default: return status.state || '未知'
  }
}

function stateVariant(status: EarlyBorrowStatus | null, loadState: EarlyBorrowLoadState): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (loadState === 'error') return 'destructive'
  if (status?.state === 'RUNNING') return 'success'
  if (status?.state === 'ERROR' || status?.state === 'SERVICE_OFFLINE') return 'destructive'
  return 'warning'
}

function CandidateRow({ row, onPush, pushing }: {
  row: EarlyBorrowCandidate
  onPush: (symbol: string) => void
  pushing: string | null
}) {
  return (
    <tr className="border-b border-border/40 last:border-0">
      <td className="px-2 py-2 font-semibold text-foreground whitespace-nowrap">{row.symbol}</td>
      <td className="px-2 py-2 text-right font-mono tabular-nums text-amber-400">{spread(row.current_spread)}</td>
      <td className="px-2 py-2 text-right font-mono tabular-nums text-primary">{pct(row.similarity_score)}</td>
      <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground">
        {row.estimated_hit_rate == null ? '待积累' : pct(row.estimated_hit_rate)}
      </td>
      <td className="px-2 py-2 text-right text-muted-foreground">{row.matched_case_count || 0}</td>
      <td className="px-2 py-2 text-right text-muted-foreground whitespace-nowrap">{formatTime(row.detected_at)}</td>
      <td className="px-2 py-2 text-right text-muted-foreground whitespace-nowrap">{formatTime(row.expires_at)}</td>
      <td className="px-2 py-2 text-right whitespace-nowrap">
        {row.status === 'suggested' ? (
          <button
            type="button"
            onClick={() => onPush(row.symbol)}
            disabled={pushing === row.symbol}
            className="rounded border border-primary/50 px-2 py-1 text-[10px] text-primary hover:bg-primary/10 disabled:opacity-50"
            title="仅加入当前用户借币列表，不会立即借币或开仓"
          >
            {pushing === row.symbol ? '推送中...' : '推送到借币列表'}
          </button>
        ) : (
          <span className="text-muted-foreground">已过期</span>
        )}
      </td>
    </tr>
  )
}

/** Public Binance case matches.  This panel intentionally has no borrow/order action. */
export function EarlyBorrowPanel() {
  const initialCache = getEarlyBorrowCache()
  const [status, setStatus] = useState<EarlyBorrowStatus | null>(initialCache?.status || null)
  const [candidates, setCandidates] = useState<EarlyBorrowCandidate[]>(initialCache?.candidates?.items || [])
  const [warnings, setWarnings] = useState<EarlyBorrowWarning[]>(initialCache?.candidates?.warnings || [])
  const [cases, setCases] = useState<EarlyBorrowCase[]>(initialCache?.cases?.items || [])
  const [loadStates, setLoadStates] = useState<Record<EarlyBorrowResource, EarlyBorrowLoadState>>(() => ({
    status: initialCache?.status ? 'ready' : 'loading',
    candidates: initialCache?.candidates ? 'ready' : 'loading',
    cases: initialCache?.cases ? 'ready' : 'loading',
  }))
  const activeLoad = useRef<AbortController | null>(null)
  const loadGeneration = useRef(0)
  const notificationRefreshTimer = useRef<number | null>(null)
  const [pushing, setPushing] = useState<string | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const load = useCallback((force = false) => {
    activeLoad.current?.abort()
    const controller = new AbortController()
    activeLoad.current = controller
    const generation = ++loadGeneration.current
    const isCurrent = () => generation === loadGeneration.current && !controller.signal.aborted

    // A warm cache is rendered synchronously. Revalidation is still forced
    // for explicit refreshes and the 15-second safety poll, but old rows stay
    // visible while the request is in flight. A fresh cache does not trigger a
    // duplicate request here: the navigation intent may already have completed
    // the same shared warm-up immediately before the modal mounted.
    const cached = getEarlyBorrowCache()
    const cacheFresh = Boolean(cached && isEarlyBorrowCacheFresh())
    if (cached && !force && cacheFresh) {
      setStatus(cached.status)
      setCandidates(cached.candidates?.items || [])
      setWarnings(cached.candidates?.warnings || [])
      setCases(cached.cases?.items || [])
      setLoadStates({ status: 'ready', candidates: 'ready', cases: 'ready' })
    }

    const applyResource = (result: EarlyBorrowResourceResult) => {
      if (!isCurrent()) return
      switch (result.resource) {
        case 'status':
          if (result.value) setStatus(result.value as EarlyBorrowStatus)
          break
        case 'candidates': {
          const value = result.value as EarlyBorrowCandidatesResponse | null
          if (value) {
            setCandidates(value.items || [])
            setWarnings(value.warnings || [])
          }
          break
        }
        case 'cases': {
          const value = result.value as EarlyBorrowCasesResponse | null
          if (value) setCases(value.items || [])
          break
        }
      }
      setLoadStates((current) => ({ ...current, [result.resource]: result.error ? 'error' : 'ready' }))
    }

    // Even a fresh snapshot is revalidated after it is painted. The cache is
    // a latency optimization, not a freshness waiver for market suggestions.
    const refresh = force || !cacheFresh
    void loadEarlyBorrowCache({ force: refresh, signal: controller.signal, onResource: applyResource }).then(({ snapshot, errors }) => {
      if (!isCurrent()) return
      if (snapshot.status) setStatus(snapshot.status)
      if (snapshot.candidates) {
        setCandidates(snapshot.candidates.items || [])
        setWarnings(snapshot.candidates.warnings || [])
      }
      if (snapshot.cases) setCases(snapshot.cases.items || [])
      setLoadStates({
        status: errors.status ? 'error' : snapshot.status ? 'ready' : 'error',
        candidates: errors.candidates ? 'error' : snapshot.candidates ? 'ready' : 'error',
        cases: errors.cases ? 'error' : snapshot.cases ? 'ready' : 'error',
      })
    }).catch(() => {
      if (!isCurrent()) return
      // Abort is a normal lifecycle event. For an actual failure, preserve
      // any cached rows and clear only the resource status indicators.
      if (!cached) setLoadStates({ status: 'error', candidates: 'error', cases: 'error' })
    })
  }, [])

  useEffect(() => {
    load()
    const timer = window.setInterval(() => load(true), 15000)
    return () => {
      loadGeneration.current += 1
      activeLoad.current?.abort()
      if (notificationRefreshTimer.current !== null) {
        window.clearTimeout(notificationRefreshTimer.current)
      }
      window.clearInterval(timer)
    }
  }, [load])

  const handlePush = useCallback(async (symbol: string) => {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized || pushing) return
    setPushing(normalized)
    try {
      await pushSymbol(normalized)
      window.dispatchEvent(new CustomEvent('pushed:refresh'))
      addToast(`${normalized} 已加入当前用户借币列表`, 'success')
    } catch (reason: unknown) {
      const message = reason as { response?: { data?: { detail?: string } }; message?: string }
      addToast(message?.response?.data?.detail || message?.message || '推送失败，请检查当前用户规则', 'error')
    } finally {
      setPushing(null)
    }
  }, [addToast, pushing])

  useEffect(() => {
    const onNotification = (event: Event) => {
      const data = (event as CustomEvent).detail as Record<string, unknown> | undefined
      if (!data || (data.type !== 'spread_warning' && data.type !== 'early_borrow')) return
      if (data.type === 'spread_warning' && data.symbol) {
        const symbol = String(data.symbol).toUpperCase()
        const warning: EarlyBorrowWarning = {
          id: `warning:${symbol}`,
          symbol,
          detected_at: typeof data.detected_at === 'string' ? data.detected_at : new Date().toISOString(),
          current_spread: typeof data.spread === 'number' ? data.spread : null,
          status: 'warning',
          expires_at: typeof data.expires_at === 'string' ? data.expires_at : null,
          note: typeof data.content === 'string' ? data.content : '点差预警仅发送提醒，不自动借币、不自动开仓',
          read_only: true,
        }
        setWarnings((current) => [warning, ...current.filter((row) => row.id !== warning.id)].slice(0, 100))
        return
      }
      if (notificationRefreshTimer.current !== null) {
        window.clearTimeout(notificationRefreshTimer.current)
      }
      notificationRefreshTimer.current = window.setTimeout(() => {
        notificationRefreshTimer.current = null
        load(true)
      }, 300)
    }
    window.addEventListener('ws:notification', onNotification)
    return () => window.removeEventListener('ws:notification', onNotification)
  }, [load])

  const cfg = status?.config
  const showWarmup = !candidates.length && status && (status.ready_case_count < 1 || status.feature_count < 3)

  return (
    <div className="px-3 pb-3">
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-2">
        <ShieldCheck size={14} className="text-amber-400" />
        <span className="text-xs font-semibold">提前借币建议</span>
        <Badge variant={stateVariant(status, loadStates.status)}>{stateLabel(status, loadStates.status)}</Badge>
        {loadStates.status === 'error' && status && (
          <span className="text-[10px] text-negative">状态更新失败，显示上次结果</span>
        )}
        <span className="text-[10px] text-muted-foreground">Binance 公共行情 · 只读</span>
        <button
          type="button"
          onClick={() => load(true)}
          className="ml-auto inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[10px] text-muted-foreground hover:bg-accent"
          title="刷新案例匹配"
        >
          <RefreshCw size={11} className={Object.values(loadStates).some((state) => state === 'loading') ? 'animate-spin' : ''} />刷新
        </button>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] sm:grid-cols-4">
        <div className="rounded border border-border/60 px-2 py-1.5"><span className="text-muted-foreground">合资格币种</span><b className="ml-1">{status?.universe_size ?? '-'}</b></div>
        <div className="rounded border border-border/60 px-2 py-1.5"><span className="text-muted-foreground">点差采样</span><b className="ml-1">{cfg?.sample_interval_sec ?? 2}s</b></div>
        <div className="rounded border border-border/60 px-2 py-1.5"><span className="text-muted-foreground">指标周期</span><b className="ml-1">{cfg?.metrics_interval_sec ? `${Math.round(cfg.metrics_interval_sec / 60)}m` : '5m'}</b></div>
        <div className="rounded border border-border/60 px-2 py-1.5"><span className="text-muted-foreground">案例/可用</span><b className="ml-1">{status ? `${status.case_count}/${status.ready_case_count}` : '-'}</b></div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
        <span>预警线 {spread(cfg?.warning_spread_pct)}</span>
        <span>借币候选 {spread(cfg?.candidate_spread_pct)}</span>
        <span>有效建议线 {spread(cfg?.effective_candidate_spread_pct)}</span>
        <span>真正开仓线 {spread(cfg?.open_spread_pct)}</span>
        <span>跳点案例 {spread(cfg?.trigger_spread_pct)}</span>
        <span>回看 {cfg?.lookback_hours ?? 6}h</span>
      </div>

      {loadStates.candidates === 'error' && (
        <div className="mt-3 flex items-center gap-2 rounded border border-negative/30 bg-negative/10 px-2 py-2 text-[10px] text-negative">
          <AlertTriangle size={12} />建议数据刷新失败{candidates.length || warnings.length ? '，当前显示上次结果' : ''}；不会影响 Worker。
        </div>
      )}

      <div className="mt-3 overflow-x-auto rounded border border-border/60">
        <table className="w-full min-w-[700px] text-[10px]">
          <thead className="bg-[#0d0d14] text-muted-foreground">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium">币种</th>
              <th className="px-2 py-1.5 text-right font-medium">当前点差</th>
              <th className="px-2 py-1.5 text-right font-medium">案例相似度</th>
              <th className="px-2 py-1.5 text-right font-medium">命中率</th>
              <th className="px-2 py-1.5 text-right font-medium">匹配案例</th>
              <th className="px-2 py-1.5 text-right font-medium">发现时间</th>
              <th className="px-2 py-1.5 text-right font-medium">建议到期</th>
              <th className="px-2 py-1.5 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {warnings.map((row) => (
              <tr key={row.id} className="border-b border-border/40 last:border-0">
                <td className="px-2 py-2 font-semibold text-amber-400 whitespace-nowrap">{row.symbol}</td>
                <td className="px-2 py-2 text-right font-mono tabular-nums text-amber-400">{spread(row.current_spread)}</td>
                <td className="px-2 py-2 text-right text-muted-foreground">-</td>
                <td className="px-2 py-2 text-right text-muted-foreground">仅提醒</td>
                <td className="px-2 py-2 text-right text-muted-foreground">-</td>
                <td className="px-2 py-2 text-right text-muted-foreground whitespace-nowrap">{formatTime(row.detected_at)}</td>
                <td className="px-2 py-2 text-right text-muted-foreground whitespace-nowrap">预警</td>
                <td className="px-2 py-2 text-right text-muted-foreground">只读</td>
              </tr>
            ))}
            {candidates.map((row) => <CandidateRow key={row.id} row={row} onPush={handlePush} pushing={pushing} />)}
            {loadStates.candidates === 'ready' && !candidates.length && !warnings.length && (
              <tr><td colSpan={8} className="px-2 py-6 text-center text-muted-foreground">
                {showWarmup ? '案例库正在预热，至少积累 0-6 小时行情与指标后才会匹配。' : '当前没有符合案例的提前借币建议。'}
              </td></tr>
            )}
            {loadStates.candidates === 'loading' && !candidates.length && !warnings.length && (
              <tr><td colSpan={8} className="px-2 py-6 text-center text-muted-foreground">建议加载中...</td></tr>
            )}
            {loadStates.candidates === 'error' && !candidates.length && !warnings.length && (
              <tr><td colSpan={8} className="px-2 py-6 text-center text-negative">建议数据暂不可用，请刷新重试。</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 rounded border border-border/60">
        <div className="flex items-center gap-1 border-b border-border/60 bg-[#0d0d14] px-2 py-1.5 text-[10px] font-medium">
          <Database size={11} className="text-muted-foreground" />最近跳点案例
          {loadStates.cases === 'loading' && <span className="ml-auto text-muted-foreground">加载中...</span>}
          {loadStates.cases === 'error' && <span className="ml-auto text-negative">更新失败</span>}
        </div>
        <div className="divide-y divide-border/40">
          {loadStates.cases === 'loading' && !cases.length && <div className="px-2 py-3 text-[10px] text-muted-foreground">案例加载中...</div>}
          {loadStates.cases === 'error' && !cases.length && <div className="px-2 py-3 text-[10px] text-negative">案例数据暂不可用，请刷新重试。</div>}
          {loadStates.cases === 'ready' && !cases.length && <div className="px-2 py-3 text-[10px] text-muted-foreground">尚无 1% 跳点案例，采集器会在 Binance 数据达到阈值后记录。</div>}
          {cases.map((row) => (
            <div key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1.5 text-[10px]">
              <b className="text-foreground">{row.symbol}</b>
              <span className="text-amber-400">跳点 {spread(row.trigger_spread)}</span>
              <span className="text-muted-foreground">样本 {row.sample_count}</span>
              <Badge variant={row.status === 'ready' ? 'success' : 'warning'}>{row.status === 'ready' ? '可匹配' : '预热中'}</Badge>
              <span className="ml-auto inline-flex items-center gap-1 text-muted-foreground"><Clock3 size={10} />{formatTime(row.trigger_at)}</span>
            </div>
          ))}
        </div>
      </div>

      <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
        这是历史案例匹配提醒。默认不自动推送；仅当规则中的“提前借币自动推送”开启时，建议才会加入当前用户的 Dashboard 币种列表。该功能不自动借币、不开仓、不修改其他用户规则。
      </p>
    </div>
  )
}
