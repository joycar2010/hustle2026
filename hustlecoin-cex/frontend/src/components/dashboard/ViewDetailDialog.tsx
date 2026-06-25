import { useMemo } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import type { Position } from '@/components/dashboard/OwlTreeTable'

/**
 * 查看详情弹窗(主界面暗色风格)。替代旧的纯 toast。
 * 真实持仓 → 展示持仓经济字段;并集伪行(id<0 或 status==PUSHED)→ 展示该子账户该币的余额/借币/可借,
 * 而非空 position 字段。
 */
export function ViewDetailDialog({ position, onClose }: {
  position: Position
  onClose: () => void
}) {
  const balances = useBalanceStore((s) => s.balances)
  const base = position.symbol.replace('USDT', '')
  const isPseudo = position.id < 0 || position.status === 'PUSHED'
  const sm = useMemo(
    () => balances.find((b) => b.account_id === position.sub_account_id)?.symbol_margin?.[position.symbol],
    [balances, position.sub_account_id, position.symbol],
  )

  const num = (v: string | number | undefined | null, digits = 4) => {
    if (v === undefined || v === null || v === '') return '-'
    const n = typeof v === 'string' ? parseFloat(v) : v
    return Number.isFinite(n) ? n.toFixed(digits) : String(v)
  }

  const fields: [string, string][] = isPseudo
    ? [
        ['账户', position.account_note || `#${position.sub_account_id}`],
        ['状态', '挂单中(无持仓)'],
        ['现币', num(sm?.free)],
        ['借币本金', num(sm?.borrowed)],
        ['利息', num(sm?.interest, 6)],
        ['最大可借(理论)', num(sm?.max_borrowable)],
        ['有效可借', num(sm?.effective_borrowable)],
        ['日利率', sm?.daily_interest_rate != null ? `${(sm.daily_interest_rate * 100).toFixed(4)}%` : '-'],
        ['库存', sm?.no_inventory ? '无券' : '有券'],
      ]
    : [
        ['账户', position.account_note || `#${position.sub_account_id}`],
        ['状态', position.status],
        ['借币量', num(position.borrow_qty)],
        ['开仓点差', position.open_spread != null ? `${num(position.open_spread, 4)}%` : '-'],
        ['开仓额(USDT)', num(position.open_usdt_amount, 2)],
        ['合约多仓量', num(position.futures_long_qty)],
        ['平点差', position.close_spread != null ? `${num(position.close_spread, 4)}%` : '-'],
        ['累计资金费', num(position.cumulative_funding_fee, 4)],
        ['累计利息', num(position.cumulative_interest, 6)],
        ['已实现盈亏', num(position.realized_pnl, 4)],
        ['开仓时间', position.opened_at || '-'],
      ]

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2" onClick={onClose}>
      <div className="w-full max-w-[440px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-[#141420] shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <span className="text-sm font-semibold">详情 — <span className="text-primary">{base}</span>
            <span className="text-muted-foreground"> · {position.account_note || `#${position.sub_account_id}`}</span>
          </span>
          <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground text-lg leading-none">✕</button>
        </div>
        <div className="px-4 py-2">
          <table className="w-full text-[12px] border-collapse">
            <tbody>
              {fields.map(([k, v]) => (
                <tr key={k} className="border-b border-border/30">
                  <td className="py-1.5 pr-3 text-muted-foreground whitespace-nowrap">{k}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-foreground">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-end border-t border-border px-4 py-3">
          <button onClick={onClose}
            className="rounded border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">关闭</button>
        </div>
      </div>
    </div>
  )
}
