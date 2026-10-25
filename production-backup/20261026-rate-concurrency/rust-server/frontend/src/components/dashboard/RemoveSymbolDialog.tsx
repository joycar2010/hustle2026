import { useState, useMemo, useCallback } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import { partialRepay, removePushedSymbol } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'

interface AcctHeld {
  accountId: number
  note: string
  free: number        // 现币:可用现币(实时)
  borrowed: number    // 借币:杠杆户实时借币本金
  interest: number
  total: number       // 待还 = 本金 + 利息
}

/**
 * 移除币种确认弹窗(主界面暗色风格,非 confirmDialog)。
 * 列出该币所有有持币/借币的子账户 → 确认后逐账户自动还币(partialRepay)→ 再整体移除推送。
 * 无持币的币种直接确认移除即可。
 */
export function RemoveSymbolDialog({ symbol, onClose, onRemoved }: {
  symbol: string
  onClose: () => void
  onRemoved: () => void
}) {
  const balances = useBalanceStore((s) => s.balances)
  const markRepaid = useBalanceStore((s) => s.markRepaid)
  const addToast = useToastStore((s) => s.addToast)
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<string>('')   // 进度提示
  const base = symbol.replace('USDT', '')

  // 该币各子账户的现币/借币(本金+利息),来自 balance 实时快照
  const rows: AcctHeld[] = useMemo(() => {
    const out: AcctHeld[] = []
    for (const b of balances) {
      const sm = b.symbol_margin?.[symbol]
      if (!sm) continue
      const free = sm.free ?? 0
      const borrowed = sm.borrowed ?? 0
      const interest = sm.interest ?? 0
      if (free > 1e-8 || borrowed + interest > 1e-8) {
        out.push({ accountId: b.account_id, note: b.note, free, borrowed, interest, total: borrowed + interest })
      }
    }
    return out.sort((a, b) => b.total - a.total)
  }, [balances, symbol])

  const needRepay = rows.filter((r) => r.total > 1e-8)

  const handleConfirm = useCallback(async () => {
    setBusy(true)
    try {
      // 1) 逐账户自动还币(只还有欠债的)
      for (const r of needRepay) {
        setStep(`还币中:${r.note} ${r.total.toFixed(4)} ${base}`)
        try {
          await partialRepay(r.accountId, symbol, r.total)
          markRepaid(r.accountId, symbol)
        } catch (e) {
          const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
          addToast(`${r.note} 还币失败: ${msg}`, 'error')
          setBusy(false); setStep('')
          return   // 还币失败则中止,不移除(避免欠债状态下移除)
        }
      }
      // 2) 还清后移除推送
      setStep('移除推送中…')
      await removePushedSymbol(symbol)
      addToast(`${base} 已${needRepay.length > 0 ? '还币并' : ''}移除`, 'success')
      onRemoved()
      onClose()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
      addToast(`移除失败: ${msg}`, 'error')
    }
    setBusy(false); setStep('')
  }, [needRepay, base, symbol, markRepaid, addToast, onRemoved, onClose])

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2" onClick={busy ? undefined : onClose}>
      <div className="w-full max-w-[560px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-[#141420] shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <span className="text-sm font-semibold">移除币种 — <span className="text-primary">{base}</span></span>
          <span className="text-[11px] text-muted-foreground">
            {needRepay.length > 0 ? `将先还清 ${needRepay.length} 个子账户的借币，再移除` : '该币无借币，确认移除'}
          </span>
          <button onClick={busy ? undefined : onClose} disabled={busy} className="ml-auto text-muted-foreground hover:text-foreground text-lg leading-none disabled:opacity-40">✕</button>
        </div>

        <div className="px-4 py-3">
          {rows.length === 0 ? (
            <p className="py-4 text-center text-[12px] text-muted-foreground">该币当前无任何子账户持币/借币，可直接移除。</p>
          ) : (
            <table className="w-full text-[11px] border-collapse">
              <thead>
                <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                  <th className="px-2 py-1.5 text-left font-medium">子账户</th>
                  <th className="px-2 py-1.5 text-right font-medium" title="当前手上可用现币(实时)">现币</th>
                  <th className="px-2 py-1.5 text-right font-medium" title="杠杆户实时借币本金">借币</th>
                  <th className="px-2 py-1.5 text-right font-medium">利息</th>
                  <th className="px-2 py-1.5 text-right font-medium">待还</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.accountId} className="border-b border-border/30">
                    <td className="px-2 py-1.5 font-medium">{r.note}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground">{r.free.toFixed(4)}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-amber-400">{r.borrowed.toFixed(4)}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted-foreground">{r.interest.toFixed(6)}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums">{r.total > 1e-8 ? r.total.toFixed(4) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {step && <p className="mt-2 text-[11px] text-primary">{step}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <button onClick={busy ? undefined : onClose} disabled={busy}
            className="rounded border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40">取消</button>
          <button onClick={handleConfirm} disabled={busy}
            className="rounded px-4 py-1.5 text-xs font-medium bg-negative/20 text-negative hover:bg-negative/30 disabled:opacity-40">
            {busy ? '处理中…' : needRepay.length > 0 ? '还币并移除' : '确认移除'}
          </button>
        </div>
      </div>
    </div>
  )
}
