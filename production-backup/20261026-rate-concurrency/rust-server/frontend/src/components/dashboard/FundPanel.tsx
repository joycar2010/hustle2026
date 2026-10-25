import { useState, useEffect } from 'react'
import { getSubAccounts } from '@/api/accounts'
import { getAccountBalance } from '@/api/engine'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { cn, formatNumber, pnlColor } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

interface SubAccount {
  id: number
  note: string
  is_enabled: boolean
  order_amount: string | null
  base_margin_amount: string | null
  single_transfer_amount: string | null
}

interface AccountBalance {
  spot_usdt_free: string
  spot_usdt_locked: string
  funding_usdt: string
  earn_total: string
  margin_level: string
  margin_usdt_free: string
  margin_usdt_borrowed: string
  futures_total_balance: string
  futures_available: string
  futures_unrealized_pnl: string
}

interface FundPanelProps {
  onTransfer: (accountId: number) => void
}

export function FundPanel({ onTransfer }: FundPanelProps) {
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [balances, setBalances] = useState<Map<number, AccountBalance>>(new Map())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getSubAccounts(true).then((data: SubAccount[]) => {
      setAccounts(data)
      setLoading(false)
      for (const a of data) {
        getAccountBalance(a.id)
          .then((b: AccountBalance) => {
            setBalances(prev => {
              const next = new Map(prev)
              next.set(a.id, b)
              return next
            })
          })
          .catch(() => {})
      }
    }).catch(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-xs text-muted-foreground py-2">加载中...</p>

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs">账户资金概览</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full md:min-w-[700px] text-[11px]">
            <thead>
              <tr className="border-b text-[10px] text-muted-foreground">
                <th className="px-3 py-1.5 text-left font-medium">账户</th>
                <th className="px-2 py-1.5 text-right font-medium">保证金水平</th>
                <th className="px-2 py-1.5 text-right font-medium">杠杆可用</th>
                <th className="px-2 py-1.5 text-right font-medium">杠杆借入</th>
                <th className="px-2 py-1.5 text-right font-medium">合约余额</th>
                <th className="px-2 py-1.5 text-right font-medium">未实现PnL</th>
                <th className="px-2 py-1.5 text-right font-medium">保底额</th>
                <th className="px-2 py-1.5 text-right font-medium">挂单单笔</th>
                <th className="px-2 py-1.5 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => {
                const b = balances.get(a.id)
                const marginLevel = parseFloat(b?.margin_level || '0')
                const riskColor = marginLevel > 2 ? 'text-positive' : marginLevel > 1.5 ? 'text-yellow-400' : 'text-negative'
                return (
                  <tr key={a.id} className="border-b border-border/30 hover:bg-accent/30">
                    <td className="px-3 py-1.5 font-medium">
                      {a.note}
                      <Badge className={cn(
                        'ml-1.5 text-[8px] px-1',
                        a.is_enabled ? 'bg-positive/20 text-positive' : 'bg-negative/20 text-negative',
                      )}>
                        {a.is_enabled ? 'ON' : 'OFF'}
                      </Badge>
                    </td>
                    <td className={cn('px-2 py-1.5 text-right tabular-nums font-medium', riskColor)}>
                      {b ? formatNumber(b.margin_level) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {b ? formatNumber(b.margin_usdt_free) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-negative">
                      {b ? formatNumber(b.margin_usdt_borrowed) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {b ? formatNumber(b.futures_total_balance) : '-'}
                    </td>
                    <td className={cn('px-2 py-1.5 text-right tabular-nums', pnlColor(b?.futures_unrealized_pnl || 0))}>
                      {b ? formatNumber(b.futures_unrealized_pnl) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {a.base_margin_amount ? formatNumber(a.base_margin_amount) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {a.order_amount ? formatNumber(a.order_amount) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      <button
                        onClick={() => onTransfer(a.id)}
                        className="text-primary hover:text-primary/80 text-[10px] underline"
                      >
                        划转
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
