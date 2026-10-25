import { Wallet, BarChart3, TrendingUp, Coins } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { useEngineStore } from '@/stores/engineStore'
import { formatNumber, formatPnl, pnlColor, cn } from '@/lib/utils'

export function SummaryCards() {
  const { openPositions, closedPositions, totalPnl, totalFundingFee } = useEngineStore()

  const cards = [
    {
      title: '当前持仓',
      value: openPositions.toString(),
      icon: Wallet,
      color: 'text-primary',
    },
    {
      title: '已平仓',
      value: closedPositions.toString(),
      icon: BarChart3,
      color: 'text-muted-foreground',
    },
    {
      title: '总 PnL',
      value: formatPnl(totalPnl),
      icon: TrendingUp,
      color: pnlColor(totalPnl),
    },
    {
      title: '累计资金费',
      value: formatNumber(totalFundingFee),
      icon: Coins,
      color: pnlColor(totalFundingFee),
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {cards.map((c) => (
        <Card key={c.title}>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="rounded-md bg-accent p-2">
              <c.icon size={18} className="text-muted-foreground" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{c.title}</p>
              <p className={cn('text-lg font-bold tabular-nums', c.color)}>{c.value}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
