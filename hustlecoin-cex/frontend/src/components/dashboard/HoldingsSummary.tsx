import { useState, useMemo, useCallback } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import { partialRepay } from '@/api/engine'
import { confirmDialog } from '@/components/ui/confirm'
import { useToastStore } from '@/components/ui/toast'

interface HeldRow {
  accountId: number
  note: string
  symbol: string
  base: string
  free: number        // 现币:当前手上可用现币(实时)
  borrowed: number    // 借币:杠杆户实时借币本金
  interest: number
  total: number
}

/** 全局持币汇总:列出所有子账户当前借了哪些币、多少,逐行单独还币。数据来自 balance 实时快照。 */
export function HoldingsSummary({ onClose }: { onClose: () => void }) {
  const balances = useBalanceStore((s) => s.balances)
  const markRepaid = useBalanceStore((s) => s.markRepaid)
  const addToast = useToastStore((s) => s.addToast)
  const [repaying, setRepaying] = useState<string | null>(null)

  const rows: HeldRow[] = useMemo(() => {
    const out: HeldRow[] = []
    for (const b of balances) {
      const sm = b.symbol_margin || {}
      for (const [symbol, m] of Object.entries(sm)) {
        const borrowed = m.borrowed ?? 0
        const interest = m.interest ?? 0
        const free = m.free ?? 0
        if (borrowed + interest > 1e-8) {
          out.push({
            accountId: b.account_id, note: b.note, symbol,
            base: symbol.replace('USDT', ''),
            free, borrowed, interest, total: borrowed + interest,
          })
        }
      }
    }
    return out.sort((a, b) => b.total - a.total)
  }, [balances])

  const handleRepay = useCallback(async (r: HeldRow) => {
    if (!(await confirmDialog({
      title: '还币',
      message: `确认为 ${r.note} 还清 ${r.base}？\n本金 ${r.borrowed.toFixed(6)} + 利息 ${r.interest.toFixed(6)} ≈ ${r.total.toFixed(6)} ${r.base}`,
      danger: true,
    }))) return
    const key = `${r.accountId}-${r.symbol}`
    setRepaying(key)
    try {
      await partialRepay(r.accountId, r.symbol, r.total)
      markRepaid(r.accountId, r.symbol)   // 乐观清零 → 该行即时消失,下次WS推送对账
      addToast(`${r.note} ${r.base} 还币已提交`, 'success')
    } catch (e) {
      addToast(`还币失败: ${(e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message}`, 'error')
    }
    setRepaying(null)
  }, [addToast, markRepaid])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2" onClick={onClose}>
      <div className="w-full max-w-[640px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-2 bg-[#0d0d14] border-b border-border sticky top-0">
          <span className="text-sm font-semibold">持币汇总</span>
          <span className="text-[11px] text-muted-foreground">共 {rows.length} 笔借币(本金+利息)</span>
          <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground text-lg leading-none">✕</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] border-collapse">
            <thead>
              <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                <th className="px-3 py-1.5 text-left font-medium">子账户</th>
                <th className="px-3 py-1.5 text-left font-medium">币种</th>
                <th className="px-3 py-1.5 text-right font-medium" title="现币:当前手上可用现币(实时)">现币</th>
                <th className="px-3 py-1.5 text-right font-medium" title="借币:杠杆户实时借币本金">借币</th>
                <th className="px-3 py-1.5 text-right font-medium">利息</th>
                <th className="px-3 py-1.5 text-right font-medium">合计</th>
                <th className="px-3 py-1.5 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">当前无持币(无借币未还)</td></tr>
              ) : rows.map((r) => {
                const key = `${r.accountId}-${r.symbol}`
                return (
                  <tr key={key} className="border-b border-border/30 hover:bg-[#1a1a22]/60">
                    <td className="px-3 py-1.5 font-medium">{r.note}</td>
                    <td className="px-3 py-1.5">{r.base}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-foreground">{r.free.toFixed(6)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-amber-400">{r.borrowed.toFixed(6)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-muted-foreground">{r.interest.toFixed(6)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums">{r.total.toFixed(6)}</td>
                    <td className="px-3 py-1.5 text-center">
                      <button
                        onClick={() => handleRepay(r)}
                        disabled={repaying === key}
                        className="px-2 py-0.5 rounded text-[10px] bg-negative/20 text-negative hover:bg-negative/30 disabled:opacity-40"
                      >{repaying === key ? '还币中' : '还币'}</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-muted-foreground/50 px-3 py-2">
          数据来自引擎实时余额快照(杠杆账户已借本金 + 已计利息);还币按"本金+利息"全额还清该币。还币后约数秒刷新。
        </p>
      </div>
    </div>
  )
}
