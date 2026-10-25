import { useEffect, useState } from 'react'
import { getPositions } from '@/api/engine'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn, formatNumber, formatPnl, formatPercent, pnlColor } from '@/lib/utils'
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
  pnl?: string
  opened_at: string
}

export function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    try {
      const data = await getPositions('ACTIVE')
      setPositions(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (!detail) return
      setPositions((prev) => {
        const idx = prev.findIndex((p) => p.id === detail.id)
        if (idx >= 0) {
          const updated = [...prev]
          updated[idx] = { ...updated[idx], ...detail }
          return updated
        }
        return [detail, ...prev]
      })
    }
    window.addEventListener('ws:position', handler)
    return () => window.removeEventListener('ws:position', handler)
  }, [])

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">当前持仓</h1>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            OPEN 持仓 ({positions.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">加载中...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="pb-2 text-left font-medium">ID</th>
                    <th className="pb-2 text-left font-medium">账户</th>
                    <th className="pb-2 text-left font-medium">币种</th>
                    <th className="pb-2 text-left font-medium">状态</th>
                    <th className="pb-2 text-right font-medium">借币量</th>
                    <th className="pb-2 text-right font-medium">开仓利差</th>
                    <th className="pb-2 text-right font-medium">资金费</th>
                    <th className="pb-2 text-right font-medium">利息</th>
                    <th className="pb-2 text-right font-medium">PnL</th>
                    <th className="pb-2 text-right font-medium">开仓时间</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.id} className="border-b border-border/50 last:border-0 hover:bg-accent/50">
                      <td className="py-1.5 tabular-nums">{p.id}</td>
                      <td className="py-1.5">{p.account_note || `#${p.sub_account_id}`}</td>
                      <td className="py-1.5 font-medium">{p.symbol}</td>
                      <td className="py-1.5">
                        <Badge className="bg-primary/20 text-primary border-primary/30 text-[10px]">
                          {p.status}
                        </Badge>
                      </td>
                      <td className="py-1.5 text-right tabular-nums">{formatNumber(p.borrow_qty, 4)}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatPercent(p.open_spread)}</td>
                      <td className={cn('py-1.5 text-right tabular-nums', pnlColor(p.cumulative_funding_fee ?? 0))}>
                        {p.cumulative_funding_fee ? formatNumber(p.cumulative_funding_fee) : '-'}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-negative">
                        {p.cumulative_interest ? formatNumber(p.cumulative_interest) : '-'}
                      </td>
                      <td className={cn('py-1.5 text-right tabular-nums font-medium', pnlColor(p.pnl ?? 0))}>
                        {p.pnl ? formatPnl(p.pnl) : '-'}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                        {dayjs(p.opened_at).format('MM-DD HH:mm')}
                      </td>
                    </tr>
                  ))}
                  {positions.length === 0 && (
                    <tr>
                      <td colSpan={10} className="py-8 text-center text-muted-foreground">
                        暂无持仓
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
