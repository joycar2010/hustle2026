import { useEffect, useState, useCallback, useMemo } from 'react'
import { getPositionsHistory } from '@/api/engine'
import { getSubAccounts } from '@/api/accounts'
import { cn, formatNumber, pnlColor } from '@/lib/utils'
import dayjs from 'dayjs'

interface HistoryPosition {
  id: number
  symbol: string
  account_note?: string
  sub_account_id: number
  borrow_qty?: string
  open_spread: string
  close_spread?: string
  realized_pnl?: string
  cumulative_funding_fee?: string
  cumulative_interest?: string
  opened_at: string
  closed_at: string
}

interface SubAccount {
  id: number
  note: string
}

interface DateGroup {
  date: string
  dateLabel: string
  dayProfit: number
  positions: HistoryPosition[]
}

export function HistoryPage() {
  const [items, setItems] = useState<HistoryPosition[]>([])
  const [loading, setLoading] = useState(true)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [accountFilter, setAccountFilter] = useState<string>('')
  const [page, setPage] = useState(1)
  const [summary, setSummary] = useState({ total_pnl: '0', total_funding_fee: '0', total_interest: '0', net_pnl: '0', count: 0 })

  useEffect(() => {
    getSubAccounts().then(setAccounts).catch(() => {})
  }, [])

  const fetchHistory = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), size: '100' }
      if (startDate) params.start_date = startDate
      if (endDate) params.end_date = endDate
      if (accountFilter) params.sub_account_id = accountFilter
      const data = await getPositionsHistory(params)
      setItems(data.positions ?? [])
      setSummary({
        total_pnl: data.total_pnl ?? '0',
        total_funding_fee: data.total_funding_fee ?? '0',
        total_interest: data.total_interest ?? '0',
        net_pnl: data.net_pnl ?? '0',
        count: data.count ?? 0,
      })
    } catch {
      setItems([])
    }
    setLoading(false)
  }, [startDate, endDate, accountFilter, page])

  useEffect(() => { fetchHistory() }, [fetchHistory])

  const totalPnl = parseFloat(summary.total_pnl)
  const totalFunding = parseFloat(summary.total_funding_fee)
  const totalInterest = parseFloat(summary.total_interest)
  const netPnl = parseFloat(summary.net_pnl)

  const groups: DateGroup[] = useMemo(() => {
    const map = new Map<string, HistoryPosition[]>()
    for (const p of items) {
      const d = dayjs(p.closed_at).format('YYYY-MM-DD')
      if (!map.has(d)) map.set(d, [])
      map.get(d)!.push(p)
    }
    const result: DateGroup[] = []
    for (const [date, positions] of map) {
      const dj = dayjs(date)
      let dayProfit = 0
      for (const p of positions) {
        const pnl = parseFloat(p.realized_pnl || '0')
        const funding = parseFloat(p.cumulative_funding_fee || '0')
        const interest = parseFloat(p.cumulative_interest || '0')
        dayProfit += pnl + funding - interest
      }
      result.push({
        date,
        dateLabel: `${dj.year()} ${dj.month() + 1}-${String(dj.date()).padStart(2, '0')}`,
        dayProfit,
        positions,
      })
    }
    return result
  }, [items])

  function fmtVal(v: string | undefined | number, decimals = 2): string {
    const n = typeof v === 'string' ? parseFloat(v) : (v ?? 0)
    if (isNaN(n)) return '0.00'
    return n.toFixed(decimals)
  }

  return (
    <div className="space-y-0">
      {/* Title bar */}
      <div className="flex items-center justify-between px-3 py-2 bg-[#0d0d14] border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">平仓历史</span>
        </div>
      </div>

      {/* Filter + Summary row */}
      <div className="flex flex-wrap items-center gap-3 px-3 py-2 text-[11px] bg-[#111118] border-b border-border">
        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setPage(1) }}
            className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
          />
          <span className="text-muted-foreground">→</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => { setEndDate(e.target.value); setPage(1) }}
            className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
          />
          <select
            value={accountFilter}
            onChange={(e) => { setAccountFilter(e.target.value); setPage(1) }}
            className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
          >
            <option value="">全部</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.note}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 ml-2 text-muted-foreground">
          <span>总利息: <span className="text-foreground">{formatNumber(totalInterest)}</span></span>
          <span>总资金费: <span className="text-foreground">{formatNumber(totalFunding)}</span></span>
          <span>总平仓利润: <span className="text-foreground">{formatNumber(totalPnl)}</span></span>
          <span>利润汇总: <span className={cn('font-medium', pnlColor(netPnl))}>{formatNumber(netPnl)}</span></span>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[700px] text-[11px] border-collapse">
          <thead>
            <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
              <th className="px-3 py-1.5 text-left font-medium w-[90px] border-r border-border/50">日期</th>
              <th className="px-3 py-1.5 text-center font-medium w-[60px] border-r-2 border-border">利润</th>
              <th className="px-3 py-1.5 text-center font-medium w-[60px]">币种</th>
              <th className="px-3 py-1.5 text-center font-medium w-[50px]">备注</th>
              <th className="px-3 py-1.5 text-center font-medium w-[120px]">平仓时间</th>
              <th className="px-3 py-1.5 text-left font-medium">汇总</th>
              <th className="px-3 py-1.5 text-right font-medium w-[70px]">利润</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">加载中...</td></tr>
            ) : groups.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">暂无平仓记录</td></tr>
            ) : groups.map((g) =>
              g.positions.map((p, idx) => {
                const pnl = parseFloat(p.realized_pnl || '0')
                const funding = parseFloat(p.cumulative_funding_fee || '0')
                const interest = parseFloat(p.cumulative_interest || '0')
                const net = pnl + funding - interest
                const isFirst = idx === 0
                return (
                  <tr key={p.id} className="border-b border-border/30 hover:bg-[#1a1a22]/60">
                    {isFirst && (
                      <>
                        <td
                          rowSpan={g.positions.length}
                          className="px-3 py-1.5 text-left align-top tabular-nums text-foreground border-r border-border/50 bg-[#0d0d14]/40"
                        >
                          {g.dateLabel}
                        </td>
                        <td
                          rowSpan={g.positions.length}
                          className={cn(
                            'px-3 py-1.5 text-center align-top tabular-nums font-mono border-r-2 border-border bg-[#0d0d14]/40',
                            pnlColor(g.dayProfit)
                          )}
                        >
                          {formatNumber(g.dayProfit)}
                        </td>
                      </>
                    )}
                    <td className="px-3 py-1.5 text-center font-medium">{p.symbol.replace('USDT', '')}</td>
                    <td className="px-3 py-1.5 text-center text-muted-foreground tabular-nums">
                      {p.account_note || p.sub_account_id}
                    </td>
                    <td className="px-3 py-1.5 text-center tabular-nums text-muted-foreground font-mono">
                      {dayjs(p.closed_at).format('MM-DD HH:mm:ss')}
                    </td>
                    <td className="px-3 py-1.5 text-left text-muted-foreground font-mono tabular-nums whitespace-nowrap">
                      <span className="text-foreground/70">开</span>{' '}
                      <span className="text-foreground">{fmtVal(p.open_spread)}</span>
                      <span className="text-foreground/30"> · </span>
                      <span className="text-foreground/70">平</span>{' '}
                      <span className="text-foreground">{fmtVal(p.close_spread)}</span>
                      <span className="text-foreground/30"> · </span>
                      <span className="text-foreground/70">息</span>{' '}
                      <span className="text-foreground">{fmtVal(p.cumulative_interest)}</span>
                      <span className="text-foreground/30"> · </span>
                      <span className="text-foreground/70">累资</span>{' '}
                      <span className="text-foreground">{fmtVal(p.cumulative_funding_fee)}</span>
                      <span className="text-foreground/30"> · </span>
                      <span className="text-foreground/70">平润</span>
                      <span className={pnlColor(pnl)}>{fmtVal(p.realized_pnl)}</span>
                    </td>
                    <td className={cn('px-3 py-1.5 text-right tabular-nums font-mono font-medium', pnlColor(net))}>
                      {formatNumber(net)}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {summary.count > 100 && (
        <div className="flex items-center gap-2 justify-center text-[11px] py-2">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page <= 1}
            className="px-2 py-0.5 rounded border border-border text-muted-foreground hover:text-foreground disabled:opacity-30"
          >
            上一页
          </button>
          <span className="text-muted-foreground">第 {page} 页</span>
          <button
            onClick={() => setPage(page + 1)}
            disabled={items.length < 100}
            className="px-2 py-0.5 rounded border border-border text-muted-foreground hover:text-foreground disabled:opacity-30"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
