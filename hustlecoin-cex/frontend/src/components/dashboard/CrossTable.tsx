import { useState, useMemo, useCallback, useEffect } from 'react'
import { useSpreadStore, type SpreadData } from '@/stores/spreadStore'
import { cn, formatNumber, formatPercent, spreadColor, pnlColor } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ContextMenu } from '@/components/dashboard/ContextMenu'
import dayjs from 'dayjs'

interface Position {
  id: number
  sub_account_id: number
  account_note?: string
  symbol: string
  status: string
  borrow_qty: string
  open_spread: string
  cumulative_funding_fee?: string
  cumulative_interest?: string
  funding_rate_ratio?: string
  realized_pnl?: string
  opened_at: string
}

interface CrossTableProps {
  positions: Position[]
  onAction: (action: string, symbol: string, position?: Position) => void
}

interface SymbolRow {
  symbol: string
  spread: SpreadData | undefined
  positions: Position[]
  totalFunding: number
  totalInterest: number
  avgRatio: number | null
}

export function CrossTable({ positions, onAction }: CrossTableProps) {
  const spreads = useSpreadStore((s) => s.spreads)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; symbol: string; position?: Position
  } | null>(null)

  const symbolRows = useMemo(() => {
    const bySymbol = new Map<string, Position[]>()
    for (const p of positions) {
      const list = bySymbol.get(p.symbol) || []
      list.push(p)
      bySymbol.set(p.symbol, list)
    }

    const allSymbols = new Set([...spreads.keys(), ...bySymbol.keys()])
    const rows: SymbolRow[] = []
    const q = search.toUpperCase()

    for (const symbol of allSymbols) {
      if (q && !symbol.includes(q)) continue
      const sp = spreads.get(symbol)
      const pos = bySymbol.get(symbol) || []
      const totalFunding = pos.reduce((s, p) => s + parseFloat(p.cumulative_funding_fee || '0'), 0)
      const totalInterest = pos.reduce((s, p) => s + parseFloat(p.cumulative_interest || '0'), 0)
      const ratios = pos.map(p => parseFloat(p.funding_rate_ratio || '')).filter(r => !isNaN(r))
      const avgRatio = ratios.length > 0 ? ratios.reduce((a, b) => a + b, 0) / ratios.length : null

      rows.push({ symbol, spread: sp, positions: pos, totalFunding, totalInterest, avgRatio })
    }

    rows.sort((a, b) => {
      if (a.positions.length !== b.positions.length) return b.positions.length - a.positions.length
      const aMax = a.spread ? Math.max(Math.abs(a.spread.spread_long), Math.abs(a.spread.spread_short)) : 0
      const bMax = b.spread ? Math.max(Math.abs(b.spread.spread_long), Math.abs(b.spread.spread_short)) : 0
      return bMax - aMax
    })

    return rows
  }, [spreads, positions, search])

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

  useEffect(() => {
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const hasPositions = symbolRows.some(r => r.positions.length > 0)
  const positionSymbols = symbolRows.filter(r => r.positions.length > 0)
  const topSpreads = symbolRows.filter(r => r.positions.length === 0).slice(0, 50)
  const displayRows = hasPositions ? [...positionSymbols, ...topSpreads] : symbolRows.slice(0, 100)

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <Input
          placeholder="搜索币种..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-48"
        />
        <span className="text-xs text-muted-foreground">
          持仓 {positionSymbols.length} 币种 · 监控 {spreads.size} 币种
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-card/50 text-[10px] text-muted-foreground">
              <th className="p-1.5 text-left font-medium w-8"></th>
              <th className="p-1.5 text-left font-medium">币种</th>
              <th className="p-1.5 text-right font-medium">开仓利差</th>
              <th className="p-1.5 text-right font-medium">平仓利差</th>
              <th className="p-1.5 text-center font-medium">持仓</th>
              <th className="p-1.5 text-right font-medium">资息倍率</th>
              <th className="p-1.5 text-right font-medium">累计资金费</th>
              <th className="p-1.5 text-right font-medium">累计利息</th>
              <th className="p-1.5 text-right font-medium">状态</th>
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row) => (
              <SymbolRowComponent
                key={row.symbol}
                row={row}
                isExpanded={expanded.has(row.symbol)}
                onToggle={toggle}
                onContextMenu={handleContextMenu}
                onAction={onAction}
              />
            ))}
            {displayRows.length === 0 && (
              <tr>
                <td colSpan={9} className="py-6 text-center text-muted-foreground text-xs">
                  {search ? '未找到匹配币种' : '等待数据...'}
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
          onAction={(action) => {
            onAction(action, contextMenu.symbol, contextMenu.position)
            setContextMenu(null)
          }}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  )
}

function SymbolRowComponent({
  row, isExpanded, onToggle, onContextMenu,
}: {
  row: SymbolRow
  isExpanded: boolean
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onAction: (action: string, symbol: string, position?: Position) => void
}) {
  const hasPos = row.positions.length > 0

  return (
    <>
      <tr
        className={cn(
          'border-b border-border/30 hover:bg-accent/30 cursor-pointer transition-colors',
          hasPos && 'bg-card/80 font-medium',
        )}
        onClick={() => hasPos && onToggle(row.symbol)}
        onContextMenu={(e) => onContextMenu(e, row.symbol)}
      >
        <td className="p-1.5 text-center text-muted-foreground">
          {hasPos ? (isExpanded ? '▾' : '▸') : '·'}
        </td>
        <td className="p-1.5 font-medium">{row.symbol.replace('USDT', '')}</td>
        <td className={cn('p-1.5 text-right tabular-nums', spreadColor(row.spread?.spread_short ?? 0))}>
          {row.spread ? formatPercent(row.spread.spread_short) : '-'}
        </td>
        <td className={cn('p-1.5 text-right tabular-nums', spreadColor(row.spread ? (row.spread.fut_bid !== 0 ? (row.spread.spot_ask - row.spread.fut_bid) / row.spread.fut_bid * 100 : 0) : 0))}>
          {row.spread ? formatPercent(row.spread.fut_bid !== 0 ? (row.spread.spot_ask - row.spread.fut_bid) / row.spread.fut_bid * 100 : 0) : '-'}
        </td>
        <td className="p-1.5 text-center">
          {hasPos ? (
            <Badge className="bg-primary/20 text-primary border-primary/30 text-[9px] px-1">
              {row.positions.length}
            </Badge>
          ) : '-'}
        </td>
        <td className="p-1.5 text-right tabular-nums">
          {row.avgRatio != null ? formatNumber(row.avgRatio, 2) : '-'}
        </td>
        <td className={cn('p-1.5 text-right tabular-nums', pnlColor(row.totalFunding))}>
          {hasPos ? formatNumber(row.totalFunding) : '-'}
        </td>
        <td className="p-1.5 text-right tabular-nums text-negative">
          {hasPos ? formatNumber(row.totalInterest) : '-'}
        </td>
        <td className="p-1.5 text-right">
          {hasPos ? (
            <Badge className="bg-positive/20 text-positive border-positive/30 text-[9px] px-1">OPEN</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </td>
      </tr>

      {isExpanded && row.positions.map((pos) => (
        <tr
          key={pos.id}
          className="border-b border-border/20 bg-background/50 hover:bg-accent/20 cursor-pointer"
          onContextMenu={(e) => onContextMenu(e, row.symbol, pos)}
        >
          <td className="p-1.5"></td>
          <td className="p-1.5 pl-6 text-muted-foreground">
            ↳ {pos.account_note || `#${pos.sub_account_id}`}
          </td>
          <td className="p-1.5 text-right tabular-nums text-muted-foreground">
            开:{formatNumber(pos.open_spread, 4)}%
          </td>
          <td className="p-1.5 text-right tabular-nums">
            {formatNumber(pos.borrow_qty, 4)}
          </td>
          <td className="p-1.5 text-center">
            <Badge className="bg-primary/15 text-primary/80 text-[9px] px-1">{pos.status}</Badge>
          </td>
          <td className="p-1.5 text-right tabular-nums">
            {pos.funding_rate_ratio ? formatNumber(pos.funding_rate_ratio, 2) : '-'}
          </td>
          <td className={cn('p-1.5 text-right tabular-nums', pnlColor(pos.cumulative_funding_fee ?? 0))}>
            {pos.cumulative_funding_fee ? formatNumber(pos.cumulative_funding_fee) : '-'}
          </td>
          <td className="p-1.5 text-right tabular-nums text-negative">
            {pos.cumulative_interest ? formatNumber(pos.cumulative_interest) : '-'}
          </td>
          <td className="p-1.5 text-right text-muted-foreground">
            {dayjs(pos.opened_at).format('MM-DD HH:mm')}
          </td>
        </tr>
      ))}
    </>
  )
}
