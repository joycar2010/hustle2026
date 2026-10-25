import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { useEngineStore } from '@/stores/engineStore'
import { cn, pnlColor, formatPnl } from '@/lib/utils'
import dayjs from 'dayjs'

export function RecentTrades() {
  const trades = useEngineStore((s) => s.recentTrades)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">最近交易</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="pb-2 text-left font-medium">时间</th>
                <th className="pb-2 text-left font-medium">币种</th>
                <th className="pb-2 text-left font-medium">操作</th>
                <th className="pb-2 text-left font-medium">账户</th>
                <th className="pb-2 text-right font-medium">PnL</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 10).map((t, i) => (
                <tr key={i} className="border-b border-border/50 last:border-0">
                  <td className="py-2 tabular-nums text-muted-foreground">
                    {t.created_at ? dayjs(t.created_at as string).format('HH:mm:ss') : '-'}
                  </td>
                  <td className="py-2 font-medium">{(t.symbol as string) || '-'}</td>
                  <td className="py-2">{(t.action as string) || '-'}</td>
                  <td className="py-2 text-muted-foreground">{(t.account_note as string) || '-'}</td>
                  <td className={cn('py-2 text-right tabular-nums', pnlColor(t.pnl as number))}>
                    {t.pnl != null ? formatPnl(t.pnl as number) : '-'}
                  </td>
                </tr>
              ))}
              {trades.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-muted-foreground">
                    暂无交易记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
