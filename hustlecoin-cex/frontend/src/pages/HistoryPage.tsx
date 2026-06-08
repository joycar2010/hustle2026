import { useEffect, useState, useCallback, useMemo, Fragment } from 'react'
import { getPositionsHistory, getTradeLogs, type TradeLogEntry } from '@/api/engine'
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
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [logsMap, setLogsMap] = useState<Map<number, TradeLogEntry[]>>(new Map())
  const [logsLoading, setLogsLoading] = useState<number | null>(null)

  const toggleDetail = useCallback((posId: number) => {
    setExpandedId((cur) => {
      if (cur === posId) return null
      if (!logsMap.has(posId)) {
        setLogsLoading(posId)
        getTradeLogs({ position_id: String(posId), size: '50' })
          .then((logs) => setLogsMap((m) => new Map(m).set(posId, logs)))
          .catch(() => setLogsMap((m) => new Map(m).set(posId, [])))
          .finally(() => setLogsLoading(null))
      }
      return posId
    })
  }, [logsMap])

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
            ) : groups.map((g) => {
              const groupHasExpanded = g.positions.some((p) => p.id === expandedId)
              const dateRowSpan = g.positions.length + (groupHasExpanded ? 1 : 0)
              return g.positions.map((p, idx) => {
                const pnl = parseFloat(p.realized_pnl || '0')
                const funding = parseFloat(p.cumulative_funding_fee || '0')
                const interest = parseFloat(p.cumulative_interest || '0')
                const net = pnl + funding - interest
                const isFirst = idx === 0
                const isExpanded = expandedId === p.id
                return (
                  <Fragment key={p.id}>
                  <tr
                    onClick={() => toggleDetail(p.id)}
                    className="border-b border-border/30 hover:bg-[#1a1a22]/60 cursor-pointer"
                  >
                    {isFirst && (
                      <>
                        <td
                          rowSpan={dateRowSpan}
                          className="px-3 py-1.5 text-left align-top tabular-nums text-foreground border-r border-border/50 bg-[#0d0d14]/40"
                        >
                          {g.dateLabel}
                        </td>
                        <td
                          rowSpan={dateRowSpan}
                          className={cn(
                            'px-3 py-1.5 text-center align-top tabular-nums font-mono border-r-2 border-border bg-[#0d0d14]/40',
                            pnlColor(g.dayProfit)
                          )}
                        >
                          {formatNumber(g.dayProfit)}
                        </td>
                      </>
                    )}
                    <td className="px-3 py-1.5 text-center font-medium">
                      <span className="text-muted-foreground mr-1">{isExpanded ? '▾' : '▸'}</span>
                      {p.symbol.replace('USDT', '')}
                    </td>
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
                  {isExpanded && (
                    <tr key={`${p.id}-detail`} className="border-b border-border/30 bg-[#0a0a10]">
                      <td colSpan={5} className="px-3 py-2">
                        {logsLoading === p.id ? (
                          <div className="text-muted-foreground text-[10px]">加载明细...</div>
                        ) : (logsMap.get(p.id)?.length ?? 0) === 0 ? (
                          <div className="text-muted-foreground text-[10px]">无执行明细</div>
                        ) : (
                          <table className="w-full text-[10px] font-mono">
                            <thead>
                              <tr className="text-muted-foreground">
                                <th className="text-left font-medium pr-3 py-0.5">动作</th>
                                <th className="text-left font-medium pr-3">方向</th>
                                <th className="text-right font-medium pr-3">数量</th>
                                <th className="text-right font-medium pr-3">价格</th>
                                <th className="text-left font-medium pr-3">订单号</th>
                                <th className="text-center font-medium pr-3">状态</th>
                                <th className="text-right font-medium pr-3">延迟ms</th>
                                <th className="text-left font-medium">时间</th>
                              </tr>
                            </thead>
                            <tbody>
                              {logsMap.get(p.id)!.map((log) => (
                                <tr key={log.id} className="border-t border-border/20">
                                  <td className="pr-3 py-0.5 text-foreground">{log.action}</td>
                                  <td className="pr-3 text-muted-foreground">{log.side || '-'}</td>
                                  <td className="pr-3 text-right tabular-nums">{log.quantity ? fmtVal(log.quantity, 4) : '-'}</td>
                                  <td className="pr-3 text-right tabular-nums">{log.price ? fmtVal(log.price, 6) : '-'}</td>
                                  <td className="pr-3 text-muted-foreground/70">{log.order_id || '-'}</td>
                                  <td className={cn('pr-3 text-center', log.status === 'SUCCESS' ? 'text-positive' : 'text-negative')}>
                                    {log.status}
                                    {log.error_message ? <span className="text-negative/70" title={log.error_message}> ⚠</span> : null}
                                  </td>
                                  <td className="pr-3 text-right tabular-nums text-muted-foreground">{log.latency_ms ?? '-'}</td>
                                  <td className="text-muted-foreground">{dayjs(log.created_at).format('HH:mm:ss')}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                  </Fragment>
                )
              })
            })}
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
