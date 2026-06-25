import { useState, useMemo, useCallback } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import { partialRepay } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'

interface Row {
  accountId: number
  note: string
  free: number        // 现币
  borrowed: number    // 借币本金
  interest: number
  total: number       // 待还 = 本金 + 利息
}

/**
 * 部分还币[指定] 弹窗(主界面暗色风格)。列出该币所有子账户的现币/借币,
 * 每行可自填还币数量单独还,或「一键全还」按本金+利息全额还清。
 */
export function PartialRepayDialog({ symbol, onClose, onDone }: {
  symbol: string
  onClose: () => void
  onDone?: () => void
}) {
  const balances = useBalanceStore((s) => s.balances)
  const markRepaid = useBalanceStore((s) => s.markRepaid)
  const addToast = useToastStore((s) => s.addToast)
  const base = symbol.replace('USDT', '')
  const [repaying, setRepaying] = useState<number | null>(null)        // 单账户还币中
  const [inputs, setInputs] = useState<Record<number, string>>({})    // 各账户输入的还币数量
  const [bulkBusy, setBulkBusy] = useState(false)

  // 该币所有子账户(全部展示,与图一致;有借币的可还)
  const rows: Row[] = useMemo(() => {
    const out: Row[] = []
    for (const b of balances) {
      const sm = b.symbol_margin?.[symbol]
      const free = sm?.free ?? 0
      const borrowed = sm?.borrowed ?? 0
      const interest = sm?.interest ?? 0
      out.push({ accountId: b.account_id, note: b.note, free, borrowed, interest, total: borrowed + interest })
    }
    return out.sort((a, b) => b.total - a.total)
  }, [balances, symbol])

  const doRepay = useCallback(async (r: Row, amount: number) => {
    if (amount <= 0) { addToast('还币数量需为正数', 'error'); return }
    setRepaying(r.accountId)
    try {
      await partialRepay(r.accountId, symbol, amount)
      markRepaid(r.accountId, symbol)
      addToast(`${r.note} ${base} 还币已提交`, 'success')
      setInputs((p) => ({ ...p, [r.accountId]: '' }))
      onDone?.()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
      addToast(`${r.note} 还币失败: ${msg}`, 'error')
    }
    setRepaying(null)
  }, [symbol, base, markRepaid, addToast, onDone])

  // 一键全还(单账户):按本金+利息全额
  const repayAllOne = useCallback((r: Row) => {
    if (r.total <= 1e-8) { addToast(`${r.note} 无借币`, 'info'); return }
    doRepay(r, r.total)
  }, [doRepay, addToast])

  // 一键全还(所有账户):逐账户全额还
  const repayAllAccounts = useCallback(async () => {
    const need = rows.filter((r) => r.total > 1e-8)
    if (need.length === 0) { addToast('当前无借币可还', 'info'); return }
    setBulkBusy(true)
    for (const r of need) {
      setRepaying(r.accountId)
      try {
        await partialRepay(r.accountId, symbol, r.total)
        markRepaid(r.accountId, symbol)
      } catch (e) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
        addToast(`${r.note} 还币失败: ${msg}`, 'error')
      }
    }
    setRepaying(null)
    setBulkBusy(false)
    addToast(`已对 ${need.length} 个子账户提交全额还币`, 'success')
    onDone?.()
  }, [rows, symbol, markRepaid, addToast, onDone])

  const cellInput = 'w-20 bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-right text-foreground focus:outline-none focus:border-primary'

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2" onClick={bulkBusy ? undefined : onClose}>
      <div className="w-full max-w-[640px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-[#141420] shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <span className="text-sm font-semibold">部分还币[指定] — 币种: <span className="text-primary">{base}</span></span>
          <span className="text-[11px] text-muted-foreground">自填数量单独还,或「一键全还」按本金+利息全额</span>
          <button onClick={bulkBusy ? undefined : onClose} disabled={bulkBusy} className="ml-auto text-muted-foreground hover:text-foreground text-lg leading-none disabled:opacity-40">✕</button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-[11px] border-collapse">
            <thead>
              <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                <th className="px-2 py-1.5 text-left font-medium">账户</th>
                <th className="px-2 py-1.5 text-right font-medium" title="当前手上可用现币(实时)">现币</th>
                <th className="px-2 py-1.5 text-right font-medium" title="杠杆户实时借币本金">借币</th>
                <th className="px-2 py-1.5 text-right font-medium" title="借币×利息合计(待还)">借币金额</th>
                <th className="px-2 py-1.5 text-center font-medium">还币数量</th>
                <th className="px-2 py-1.5 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const hasDebt = r.total > 1e-8
                return (
                  <tr key={r.accountId} className="border-b border-border/30 hover:bg-accent/10">
                    <td className="px-2 py-1.5 font-medium whitespace-nowrap">{r.note}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground">{r.free > 1e-8 ? r.free.toFixed(4) : 0}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-amber-400">{r.borrowed > 1e-8 ? r.borrowed.toFixed(4) : 0}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums">{hasDebt ? r.total.toFixed(4) : 0}</td>
                    <td className="px-2 py-1.5 text-center">
                      <input
                        className={cellInput}
                        placeholder={hasDebt ? r.total.toFixed(2) : '0'}
                        value={inputs[r.accountId] ?? ''}
                        disabled={!hasDebt || bulkBusy}
                        onChange={(e) => setInputs((p) => ({ ...p, [r.accountId]: e.target.value }))}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-center whitespace-nowrap">
                      <button
                        onClick={() => {
                          const raw = (inputs[r.accountId] ?? '').trim()
                          if (raw === '') { doRepay(r, r.total); return }   // 留空=全额还
                          const v = parseFloat(raw)
                          if (isNaN(v) || v <= 0) { addToast('还币数量需为正数', 'error'); return }
                          if (v > r.total + 1e-8) {   // 超过待还(本金+利息)→ 提醒,不提交
                            addToast(`${r.note} 还币数量 ${v} 超过待还 ${r.total.toFixed(4)} ${base},请重新输入`, 'error')
                            return
                          }
                          doRepay(r, v)
                        }}
                        disabled={!hasDebt || repaying === r.accountId || bulkBusy}
                        className="px-2 py-0.5 rounded text-[10px] bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-40 mr-1"
                      >{repaying === r.accountId ? '还币中' : '还币'}</button>
                      <button
                        onClick={() => repayAllOne(r)}
                        disabled={!hasDebt || repaying === r.accountId || bulkBusy}
                        className="px-2 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 disabled:opacity-40"
                      >一键全还</button>
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">无子账户</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <button onClick={bulkBusy ? undefined : onClose} disabled={bulkBusy}
            className="rounded border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40">关闭</button>
          <button onClick={repayAllAccounts} disabled={bulkBusy}
            className="rounded px-4 py-1.5 text-xs font-medium bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 disabled:opacity-40">
            {bulkBusy ? '处理中…' : '全部账户一键全还'}
          </button>
        </div>
      </div>
    </div>
  )
}
