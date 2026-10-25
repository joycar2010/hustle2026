import { useState, useMemo, useCallback } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import { manualOpen } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'

interface Row {
  accountId: number
  note: string
  free: number        // 现币
  borrowed: number    // 借币本金
}

/**
 * 手动开仓弹窗(主界面暗色风格)。列出该币所有子账户:点某账户「开仓」即按规则(全局/单一)对它开仓,
 * 或「一键全开」对所有子账户按规则开仓。金额留空=按全局规则,可在顶部填覆盖金额(可选)。
 * 替代旧的两段 prompt(输序号+输金额)。
 */
export function ManualOpenDialog({ symbol, onClose, onDone }: {
  symbol: string
  onClose: () => void
  onDone?: () => void
}) {
  const balances = useBalanceStore((s) => s.balances)
  const addToast = useToastStore((s) => s.addToast)
  const base = symbol.replace('USDT', '')
  const [opening, setOpening] = useState<number | null>(null)   // 单账户开仓中
  const [bulkBusy, setBulkBusy] = useState(false)
  const [amtOverride, setAmtOverride] = useState('')            // 覆盖金额(可选,留空=按规则)

  const rows: Row[] = useMemo(() => {
    return balances.map((b) => {
      const sm = b.symbol_margin?.[symbol]
      return { accountId: b.account_id, note: b.note, free: sm?.free ?? 0, borrowed: sm?.borrowed ?? 0 }
    })
  }, [balances, symbol])

  const parseAmt = useCallback((): number | undefined | null => {
    const raw = amtOverride.trim()
    if (!raw) return undefined           // 留空 = 按规则
    const v = parseFloat(raw)
    if (isNaN(v) || v <= 0) { addToast('覆盖金额需为正数(或留空按规则)', 'error'); return null }
    return v
  }, [amtOverride, addToast])

  const openOne = useCallback(async (r: Row) => {
    const amt = parseAmt()
    if (amt === null) return
    setOpening(r.accountId)
    try {
      const res = await manualOpen(r.accountId, symbol, amt)
      if (res.status === 'OPEN') addToast(`${r.note} ${base} 开仓成功`, 'success')
      else addToast(`${r.note} 开仓未完成: ${res.message || res.status}`, 'error')   // FAILED 显形,不当成功
      onDone?.()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
      addToast(`${r.note} 开仓失败: ${msg}`, 'error')
    }
    setOpening(null)
  }, [symbol, base, parseAmt, addToast, onDone])

  const openAll = useCallback(async () => {
    const amt = parseAmt()
    if (amt === null) return
    if (rows.length === 0) { addToast('无可用子账户', 'info'); return }
    setBulkBusy(true)
    let ok = 0, bad = 0
    for (const r of rows) {
      setOpening(r.accountId)
      try {
        const res = await manualOpen(r.accountId, symbol, amt)
        if (res.status === 'OPEN') ok++; else bad++
      } catch { bad++ }
    }
    setOpening(null)
    setBulkBusy(false)
    addToast(`一键开仓完成: 成功 ${ok}${bad ? `，未完成 ${bad}` : ''}`, bad ? 'error' : 'success')
    onDone?.()
  }, [rows, symbol, parseAmt, addToast, onDone])

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2" onClick={bulkBusy ? undefined : onClose}>
      <div className="w-full max-w-[560px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-[#141420] shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <span className="text-sm font-semibold">手动开仓 — 币种: <span className="text-primary">{base}</span></span>
          <span className="text-[11px] text-muted-foreground">点账户按规则开仓，或「一键全开」</span>
          <button onClick={bulkBusy ? undefined : onClose} disabled={bulkBusy} className="ml-auto text-muted-foreground hover:text-foreground text-lg leading-none disabled:opacity-40">✕</button>
        </div>

        <div className="flex items-center gap-2 px-4 py-2 border-b border-border/50 text-[11px]">
          <span className="text-muted-foreground">覆盖金额(USDT，可选):</span>
          <input
            className="w-28 bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-right text-foreground focus:outline-none focus:border-primary"
            placeholder="留空=按规则"
            value={amtOverride}
            disabled={bulkBusy}
            onChange={(e) => setAmtOverride(e.target.value)}
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-[11px] border-collapse">
            <thead>
              <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                <th className="px-2 py-1.5 text-left font-medium">账户</th>
                <th className="px-2 py-1.5 text-right font-medium" title="当前现币(实时)">现币</th>
                <th className="px-2 py-1.5 text-right font-medium" title="当前借币本金(实时)">借币</th>
                <th className="px-2 py-1.5 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.accountId} className="border-b border-border/30 hover:bg-accent/10">
                  <td className="px-2 py-1.5 font-medium whitespace-nowrap">{r.note}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground">{r.free > 1e-8 ? r.free.toFixed(4) : 0}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-amber-400">{r.borrowed > 1e-8 ? r.borrowed.toFixed(4) : 0}</td>
                  <td className="px-2 py-1.5 text-center whitespace-nowrap">
                    <button
                      onClick={() => openOne(r)}
                      disabled={opening === r.accountId || bulkBusy}
                      className="px-2.5 py-0.5 rounded text-[10px] bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-40"
                    >{opening === r.accountId ? '开仓中' : '开仓'}</button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">无子账户</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <button onClick={bulkBusy ? undefined : onClose} disabled={bulkBusy}
            className="rounded border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40">关闭</button>
          <button onClick={openAll} disabled={bulkBusy || rows.length === 0}
            className="rounded px-4 py-1.5 text-xs font-medium bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-40">
            {bulkBusy ? '处理中…' : '一键开仓全部子账户'}
          </button>
        </div>
      </div>
    </div>
  )
}
