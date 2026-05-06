import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react'
import { MoreVertical, Eye, EyeOff } from 'lucide-react'
import { useSpreadStore, type SpreadData } from '@/stores/spreadStore'
import { useBalanceStore, type AccountBalance } from '@/stores/balanceStore'
import { useUiStore } from '@/stores/uiStore'
import { cn, formatNumber, formatPercent, pnlColor, spreadColor } from '@/lib/utils'
import { useIsMobile } from '@/hooks/useIsMobile'
import { ContextMenu } from './ContextMenu'

export interface Position {
  id: number
  sub_account_id: number
  account_note?: string
  symbol: string
  status: string
  borrow_qty: string
  open_spread: string
  open_usdt_amount?: string
  cumulative_funding_fee?: string
  cumulative_interest?: string
  funding_rate_ratio?: string
  realized_pnl?: string
  opened_at: string
  close_spread?: string
}

export interface SymbolRuleInfo {
  allow_remove: boolean
  allow_repay: boolean
  open_spread: number | null
  close_spread: number | null
  order_amount: number | null
  source: string
}

interface OwlTreeTableProps {
  positions: Position[]
  pushedSymbols: string[]
  symbolRules?: Map<string, SymbolRuleInfo>
  delistingSymbols?: Set<string>
  onAction: (action: string, symbol: string, position?: Position, extra?: Record<string, unknown>) => void
}

interface SymbolGroup {
  symbol: string
  spread: SpreadData | undefined
  positions: Position[]
  totalQty: number
  totalUsdt: number
  totalFunding: number
  totalInterest: number
  totalProfit: number
  avgRatio: number | null
  isPushed: boolean
  openCount: number
  durationHours: number | null
  pushTime: string | null
  minMarginLevel: number | null
  ruleInfo: SymbolRuleInfo | null
}

function useFlash(_key: string, value: string | number | undefined) {
  const prev = useRef(value)
  const [flashing, setFlashing] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    if (prev.current !== value && prev.current !== undefined && value !== undefined) {
      setFlashing(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setFlashing(false), 1000)
    }
    prev.current = value
  }, [value])

  return flashing ? 'animate-flash' : ''
}

function durationText(opened: string): string {
  const diff = Date.now() - new Date(opened).getTime()
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  if (h > 24) return `${Math.floor(h / 24)}d${h % 24}h`
  return `${h}h${m}m`
}

function avgDurationHours(positions: Position[]): number | null {
  if (positions.length === 0) return null
  const total = positions.reduce((s, p) => {
    return s + (Date.now() - new Date(p.opened_at).getTime())
  }, 0)
  return total / positions.length / 3600000
}

// ─── Staleness banner (P2-13) ───

function StalenessBanner() {
  const wsConnected = useUiStore((s) => s.wsConnected)
  const lastUpdateTs = useBalanceStore((s) => s.lastUpdateTs)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (wsConnected) { setElapsed(0); return }
    const t = setInterval(() => {
      setElapsed(lastUpdateTs ? Math.floor((Date.now() - lastUpdateTs) / 1000) : 0)
    }, 1000)
    return () => clearInterval(t)
  }, [wsConnected, lastUpdateTs])

  if (wsConnected || elapsed < 30) return null

  return (
    <div className="flex items-center gap-2 px-2 py-1 bg-yellow-500/10 text-yellow-500 text-[10px] border-b border-yellow-500/20 shrink-0">
      数据可能过期 — 最后更新 {elapsed}s 前
    </div>
  )
}

function ruleTooltip(rule: SymbolRuleInfo): string {
  const parts: string[] = []
  if (rule.open_spread != null) parts.push(`开仓: ${rule.open_spread}%`)
  if (rule.close_spread != null) parts.push(`平仓: ${rule.close_spread}%`)
  if (rule.order_amount != null) parts.push(`金额: ${rule.order_amount}`)
  parts.push(`移除: ${rule.allow_remove ? '允许' : '禁止'}`)
  parts.push(`还币: ${rule.allow_repay ? '允许' : '禁止'}`)
  parts.push(`来源: ${rule.source}`)
  return parts.join('\n')
}

// ─── CoinHeaderRow ───

const CoinHeaderRow = memo(function CoinHeaderRow({
  group,
  isExpanded,
  isMobile,
  isDelisting,
  onToggle,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
}: {
  group: SymbolGroup
  isExpanded: boolean
  isMobile: boolean
  isDelisting?: boolean
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
}) {
  const hasPos = group.positions.length > 0
  const spreadFlash = useFlash(`${group.symbol}-ss`, group.spread?.spread_short)

  const coinName = group.symbol.replace('USDT', '')
  const dh = group.durationHours
  const dhText = dh != null ? (dh > 24 ? `${Math.floor(dh / 24)}d${Math.floor(dh % 24)}h` : `${Math.floor(dh)}h`) : '-'

  const rule = group.ruleInfo
  const hasCustomRule = rule && rule.source === 'custom' && (rule.open_spread != null || rule.close_spread != null)

  return (
    <tr
      className={cn(
        'border-b border-border/30 hover:bg-accent/20 cursor-pointer transition-colors text-[11px]',
        hasPos ? 'bg-[#111118]' : 'bg-[#0d0d14]/50',
      )}
      onClick={() => onToggle(group.symbol)}
      onDoubleClick={() => onDoubleClick(group.symbol)}
      onContextMenu={(e) => onContextMenu(e, group.symbol)}
    >
      {/* expand toggle */}
      <td className="px-1.5 py-1 text-center text-muted-foreground w-5">
        {hasPos ? (isExpanded ? '▾' : '▸') : '·'}
      </td>
      {/* 币种 */}
      <td className={cn('px-1.5 py-1 font-medium whitespace-nowrap', isDelisting ? 'text-red-500' : 'text-foreground')}>
        {coinName}
        {hasPos && (
          <span className="ml-1 text-[9px] text-muted-foreground">×{group.openCount}</span>
        )}
        {isMobile && hasPos && (
          <span className="ml-1 text-[9px] text-muted-foreground">{dhText}</span>
        )}
      </td>
      {/* 开 — spread_short (real-time opening spread) */}
      <td className={cn('px-1 py-1 text-right tabular-nums font-mono text-[10px]', spreadFlash)}>
        <span className={spreadColor(group.spread?.spread_short ?? 0)}>
          {group.spread ? formatPercent(group.spread.spread_short) : '-'}
        </span>
      </td>
      {/* 平 — spread_long (real-time closing spread) */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          <span className={spreadColor(group.spread?.spread_long ?? 0)}>
            {group.spread ? formatPercent(group.spread.spread_long) : '-'}
          </span>
        </td>
      )}
      {/* 借币 */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalQty > 0 ? formatNumber(group.totalQty, 4) : '-'}
        </td>
      )}
      {/* 金额 */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalUsdt > 0 ? formatNumber(group.totalUsdt, 0) : '-'}
        </td>
      )}
      {/* 资息 — avg funding/interest ratio */}
      <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
        {group.avgRatio != null ? formatNumber(group.avgRatio, 2) : '-'}
      </td>
      {/* 推/时 — push time or duration */}
      {!isMobile && (
        <td className="px-1 py-1 text-right whitespace-nowrap text-[10px]">
          {group.pushTime ? (
            <span className="text-muted-foreground">{group.pushTime}</span>
          ) : hasPos ? (
            <span className="text-muted-foreground">{dhText}</span>
          ) : group.isPushed ? (
            <span className="text-primary text-[9px]">已推</span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
      )}
      {/* 风险 — aggregated margin level */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.minMarginLevel != null ? (
            <span className={group.minMarginLevel > 2 ? 'text-positive' : group.minMarginLevel > 1.3 ? 'text-yellow-400' : 'text-negative'}>
              {formatNumber(group.minMarginLevel, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 单 — custom rule indicator */}
      {!isMobile && (
        <td className="px-0.5 py-1 text-center text-[9px] whitespace-nowrap" title={rule ? ruleTooltip(rule) : undefined}>
          {hasCustomRule ? (
            <span className="text-amber-400">
              {rule!.open_spread != null ? `开${rule!.open_spread}` : ''}
              {rule!.open_spread != null && rule!.close_spread != null ? ' ' : ''}
              {rule!.close_spread != null ? `平${rule!.close_spread}` : ''}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 移 — allow_remove */}
      {!isMobile && (
        <td className="px-0.5 py-1 text-center text-[10px]">
          {rule ? (
            <span className={rule.allow_remove ? 'text-positive' : 'text-negative'}>●</span>
          ) : (
            <span className="text-positive">●</span>
          )}
        </td>
      )}
      {/* 还 — allow_repay */}
      {!isMobile && (
        <td className="px-0.5 py-1 text-center text-[10px]">
          {rule ? (
            <span className={rule.allow_repay ? 'text-positive' : 'text-negative'}>●</span>
          ) : (
            <span className="text-positive">●</span>
          )}
        </td>
      )}
      {/* 资金费 */}
      <td className={cn('px-1 py-1 text-right tabular-nums font-mono text-[10px]', pnlColor(group.totalFunding))}>
        {hasPos ? formatNumber(group.totalFunding) : '-'}
      </td>
      {/* 利息 */}
      <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px] text-negative">
        {group.totalInterest > 0 ? formatNumber(group.totalInterest) : '-'}
      </td>
      {/* 利润 */}
      <td className={cn('px-1 py-1 text-right tabular-nums font-mono text-[11px] font-medium', pnlColor(group.totalProfit))}>
        {hasPos ? formatNumber(group.totalProfit) : '-'}
      </td>
      {/* mobile action button */}
      {isMobile && (
        <td className="px-0.5 py-1 text-center">
          <button
            onClick={(e) => { e.stopPropagation(); onMobileMenu(e, group.symbol) }}
            className="p-1 rounded hover:bg-accent/50 text-muted-foreground"
          >
            <MoreVertical size={14} />
          </button>
        </td>
      )}
    </tr>
  )
})

// ─── SubAccountRow ───

const SubAccountRow = memo(function SubAccountRow({
  pos,
  spread,
  balance,
  isMobile,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
}: {
  pos: Position
  spread?: SpreadData
  balance?: AccountBalance
  isMobile: boolean
  onContextMenu: (e: React.MouseEvent, symbol: string, position: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
}) {
  const fundingFlash = useFlash(`pos-${pos.id}-f`, pos.cumulative_funding_fee)
  const interestFlash = useFlash(`pos-${pos.id}-i`, pos.cumulative_interest)

  const funding = parseFloat(pos.cumulative_funding_fee || '0')
  const interest = parseFloat(pos.cumulative_interest || '0')
  const profit = funding - interest

  return (
    <tr
      className="border-b border-border/10 hover:bg-accent/10 cursor-pointer text-[11px] bg-[#0c0c11]"
      onDoubleClick={() => onDoubleClick(pos.symbol, pos.sub_account_id)}
      onContextMenu={(e) => onContextMenu(e, pos.symbol, pos)}
    >
      <td className="px-1.5 py-0.5"></td>
      {/* 币种 → account note */}
      <td className="px-1.5 py-0.5 pl-4 text-muted-foreground whitespace-nowrap">
        ↳ {pos.account_note || `#${pos.sub_account_id}`}
        {isMobile && (
          <span className="ml-1 text-[9px]">{durationText(pos.opened_at)}</span>
        )}
      </td>
      {/* 开 — open_spread (spread at which position was opened) */}
      <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px] text-muted-foreground">
        {formatNumber(pos.open_spread, 4)}%
      </td>
      {/* 平 — current close spread (spread_long) */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {spread ? (
            <span className={spreadColor(spread.spread_long)}>
              {formatPercent(spread.spread_long)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 借币 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {formatNumber(pos.borrow_qty, 4)}
        </td>
      )}
      {/* 金额 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {pos.open_usdt_amount ? formatNumber(pos.open_usdt_amount) : '-'}
        </td>
      )}
      {/* 资息 — funding rate ratio */}
      <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
        {pos.funding_rate_ratio ? formatNumber(pos.funding_rate_ratio, 2) : '-'}
      </td>
      {/* 推/时 → duration */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right text-muted-foreground whitespace-nowrap text-[10px]">
          {durationText(pos.opened_at)}
        </td>
      )}
      {/* 风险 — margin level */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance ? (
            <span className={balance.margin_level > 2 ? 'text-positive' : balance.margin_level > 1.3 ? 'text-yellow-400' : 'text-negative'}>
              {formatNumber(balance.margin_level, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 单 — empty for sub-account rows */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 移 — empty */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 还 — empty */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 资金费 */}
      <td className={cn('px-1 py-0.5 text-right tabular-nums font-mono text-[10px]', fundingFlash, pnlColor(funding))}>
        {pos.cumulative_funding_fee ? formatNumber(funding) : '-'}
      </td>
      {/* 利息 */}
      <td className={cn('px-1 py-0.5 text-right tabular-nums font-mono text-[10px] text-negative', interestFlash)}>
        {interest > 0 ? formatNumber(interest) : '-'}
      </td>
      {/* 利润 */}
      <td className={cn('px-1 py-0.5 text-right tabular-nums font-mono text-[10px]', pnlColor(profit))}>
        {(pos.cumulative_funding_fee || pos.cumulative_interest) ? formatNumber(profit) : '-'}
      </td>
      {/* mobile action button */}
      {isMobile && (
        <td className="px-0.5 py-0.5 text-center">
          <button
            onClick={(e) => { e.stopPropagation(); onMobileMenu(e, pos.symbol, pos) }}
            className="p-1 rounded hover:bg-accent/50 text-muted-foreground"
          >
            <MoreVertical size={12} />
          </button>
        </td>
      )}
    </tr>
  )
})

// ─── Main OwlTreeTable ───

const FILTER_KEY = 'hc_filter_positions_only'

export function OwlTreeTable({ positions, pushedSymbols, symbolRules, delistingSymbols, onAction }: OwlTreeTableProps) {
  const spreads = useSpreadStore((s) => s.spreads)
  const balances = useBalanceStore((s) => s.balances)
  const wsConnected = useUiStore((s) => s.wsConnected)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [showPositionsOnly, setShowPositionsOnly] = useState(() => {
    try { return localStorage.getItem(FILTER_KEY) === 'true' } catch { return false }
  })
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; symbol: string; position?: Position
  } | null>(null)
  const isMobile = useIsMobile()

  const pushedSet = useMemo(() => new Set(pushedSymbols), [pushedSymbols])

  const balanceMap = useMemo(() => {
    const m = new Map<number, AccountBalance>()
    for (const b of balances) m.set(b.account_id, b)
    return m
  }, [balances])

  const toggleFilter = useCallback(() => {
    setShowPositionsOnly(prev => {
      const next = !prev
      try { localStorage.setItem(FILTER_KEY, String(next)) } catch { /* ignore */ }
      return next
    })
  }, [])

  const groups = useMemo(() => {
    const bySymbol = new Map<string, Position[]>()
    for (const p of positions) {
      const list = bySymbol.get(p.symbol) || []
      list.push(p)
      bySymbol.set(p.symbol, list)
    }

    const allSymbols = new Set([...bySymbol.keys(), ...pushedSet])
    const q = search.toUpperCase()
    const result: SymbolGroup[] = []

    for (const symbol of allSymbols) {
      if (q && !symbol.includes(q)) continue
      const sp = spreads.get(symbol)
      const pos = bySymbol.get(symbol) || []

      if (showPositionsOnly && pos.length === 0) continue

      const totalQty = pos.reduce((s, p) => s + parseFloat(p.borrow_qty || '0'), 0)
      const totalUsdt = pos.reduce((s, p) => s + parseFloat(p.open_usdt_amount || '0'), 0)
      const totalFunding = pos.reduce((s, p) => s + parseFloat(p.cumulative_funding_fee || '0'), 0)
      const totalInterest = pos.reduce((s, p) => s + parseFloat(p.cumulative_interest || '0'), 0)
      const totalProfit = totalFunding - totalInterest
      const ratios = pos.map(p => parseFloat(p.funding_rate_ratio || '')).filter(r => !isNaN(r))
      const avgRatio = ratios.length > 0 ? ratios.reduce((a, b) => a + b, 0) / ratios.length : null
      const dh = avgDurationHours(pos)

      // Aggregate min margin level across accounts for this symbol
      const accountIds = [...new Set(pos.map(p => p.sub_account_id))]
      const marginLevels = accountIds
        .map(id => balanceMap.get(id)?.margin_level)
        .filter((v): v is number => v != null && v > 0)
      const minMarginLevel = marginLevels.length > 0 ? Math.min(...marginLevels) : null

      const earliest = pos.length > 0
        ? pos.reduce((min, p) => {
            const t = new Date(p.opened_at).getTime()
            return t < min ? t : min
          }, Infinity)
        : null
      const pushTime = earliest && earliest < Infinity
        ? new Date(earliest).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        : null

      const ruleInfo = symbolRules?.get(symbol) ?? null

      result.push({
        symbol, spread: sp, positions: pos,
        totalQty, totalUsdt, totalFunding, totalInterest, totalProfit, avgRatio,
        isPushed: pushedSet.has(symbol),
        openCount: pos.length,
        durationHours: dh,
        pushTime,
        minMarginLevel,
        ruleInfo,
      })
    }

    result.sort((a, b) => {
      if (a.positions.length !== b.positions.length) return b.positions.length - a.positions.length
      if (a.isPushed !== b.isPushed) return a.isPushed ? -1 : 1
      return (a.symbol < b.symbol ? -1 : 1)
    })

    return result
  }, [spreads, positions, search, pushedSet, showPositionsOnly, balanceMap, symbolRules])

  const toggle = useCallback((symbol: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }, [])

  const handleContextMenu = useCallback((e: React.MouseEvent, symbol: string, position?: Position) => {
    e.preventDefault()
    setContextMenu({ x: e.clientX, y: e.clientY, symbol, position })
  }, [])

  const handleMobileMenu = useCallback((e: React.MouseEvent, symbol: string, position?: Position) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setContextMenu({ x: rect.left, y: rect.bottom, symbol, position })
  }, [])

  const handleDoubleClick = useCallback((symbol: string, subAccountId?: number) => {
    onAction('set_rule', symbol, undefined, subAccountId ? { initialAccountId: subAccountId } : undefined)
  }, [onAction])

  useEffect(() => {
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const expandAll = useCallback(() => {
    setExpanded(new Set(groups.filter(g => g.positions.length > 0).map(g => g.symbol)))
  }, [groups])

  const collapseAll = useCallback(() => {
    setExpanded(new Set())
  }, [])

  const posCount = groups.filter(g => g.positions.length > 0).length
  const totalUsdt = groups.reduce((s, g) => s + g.totalUsdt, 0)
  const totalFunding = groups.reduce((s, g) => s + g.totalFunding, 0)
  const totalInterest = groups.reduce((s, g) => s + g.totalInterest, 0)
  const totalProfit = totalFunding - totalInterest

  const colCount = isMobile ? 8 : 16

  return (
    <div className="flex flex-col h-full">
      {/* Staleness banner */}
      <StalenessBanner />

      {/* Summary bar */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 py-1.5 text-[11px] text-muted-foreground border-b border-border shrink-0">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索..."
          className="w-28 bg-transparent border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
        />
        <button
          onClick={expandAll}
          className="px-1.5 py-0.5 rounded border border-border text-[10px] hover:bg-accent/50"
          title="全部展开"
        >全展</button>
        <button
          onClick={collapseAll}
          className="px-1.5 py-0.5 rounded border border-border text-[10px] hover:bg-accent/50"
          title="全部折叠"
        >全收</button>
        <button
          onClick={toggleFilter}
          className={cn(
            'px-1.5 py-0.5 rounded border text-[10px] inline-flex items-center gap-1',
            showPositionsOnly
              ? 'border-primary text-primary bg-primary/10'
              : 'border-border hover:bg-accent/50',
          )}
          title={showPositionsOnly ? '显示全部币种' : '仅显示有持仓/借币'}
        >
          {showPositionsOnly ? <Eye size={10} /> : <EyeOff size={10} />}
          {showPositionsOnly ? '显' : '隐'}
        </button>
        <span>持仓 <span className="text-foreground">{posCount}</span> 币种</span>
        <span>推送 <span className="text-primary">{pushedSymbols.length}</span></span>
        <span>金额 <span className="text-foreground font-mono">{formatNumber(totalUsdt, 0)}</span></span>
        <span className={pnlColor(totalFunding)}>资金费 {formatNumber(totalFunding)}</span>
        <span className="text-negative">利息 {formatNumber(totalInterest)}</span>
        <span className={cn('font-medium', pnlColor(totalProfit))}>利润 {formatNumber(totalProfit)}</span>
      </div>

      {/* Table */}
      <div className={cn('flex-1 overflow-auto', !wsConnected && 'opacity-60')}>
        <table className={cn('w-full', !isMobile && 'min-w-[900px]')}>
          <thead className="sticky top-0 z-10">
            <tr className="bg-[#0d0d14] text-[10px] text-muted-foreground border-b border-border">
              <th className="px-1.5 py-1 text-left font-medium w-5"></th>
              <th className="px-1.5 py-1 text-left font-medium">币种</th>
              <th className="px-1 py-1 text-right font-medium">开</th>
              {!isMobile && <th className="px-1 py-1 text-right font-medium">平</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">借币</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">金额</th>}
              <th className="px-1 py-1 text-right font-medium">资息</th>
              {!isMobile && <th className="px-1 py-1 text-right font-medium">推/时</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">风险</th>}
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">单</th>}
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">移</th>}
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">还</th>}
              <th className="px-1 py-1 text-right font-medium">资金费</th>
              <th className="px-1 py-1 text-right font-medium">利息</th>
              <th className="px-1 py-1 text-right font-medium">利润</th>
              {isMobile && <th className="px-0.5 py-1 w-7"></th>}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const isExp = expanded.has(g.symbol)
              return (
                <CoinGroupRows
                  key={g.symbol}
                  group={g}
                  isExpanded={isExp}
                  isMobile={isMobile}
                  isDelisting={delistingSymbols?.has(g.symbol)}
                  balanceMap={balanceMap}
                  spreads={spreads}
                  onToggle={toggle}
                  onContextMenu={handleContextMenu}
                  onDoubleClick={handleDoubleClick}
                  onMobileMenu={handleMobileMenu}
                />
              )
            })}
            {groups.length === 0 && (
              <tr>
                <td colSpan={colCount} className="py-8 text-center text-muted-foreground text-xs">
                  {search ? '未找到匹配币种' : showPositionsOnly ? '没有持仓币种' : '等待数据...'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          symbol={contextMenu.symbol}
          position={contextMenu.position}
          isPushed={pushedSet.has(contextMenu.symbol)}
          isAccountRow={!!contextMenu.position}
          subAccountId={contextMenu.position?.sub_account_id}
          onAction={(action, extra) => {
            onAction(action, contextMenu.symbol, contextMenu.position, extra)
            setContextMenu(null)
          }}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  )
}

const CoinGroupRows = memo(function CoinGroupRows({
  group,
  isExpanded,
  isMobile,
  isDelisting,
  balanceMap,
  spreads,
  onToggle,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
}: {
  group: SymbolGroup
  isExpanded: boolean
  isMobile: boolean
  isDelisting?: boolean
  balanceMap: Map<number, AccountBalance>
  spreads: Map<string, SpreadData>
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
}) {
  return (
    <>
      <CoinHeaderRow
        group={group}
        isExpanded={isExpanded}
        isMobile={isMobile}
        isDelisting={isDelisting}
        onToggle={onToggle}
        onContextMenu={onContextMenu}
        onDoubleClick={onDoubleClick}
        onMobileMenu={onMobileMenu}
      />
      {isExpanded && group.positions.map((pos) => (
        <SubAccountRow
          key={pos.id}
          pos={pos}
          spread={spreads.get(pos.symbol)}
          balance={balanceMap.get(pos.sub_account_id)}
          isMobile={isMobile}
          onContextMenu={onContextMenu}
          onDoubleClick={onDoubleClick}
          onMobileMenu={onMobileMenu}
        />
      ))}
    </>
  )
})
