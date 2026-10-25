import { useState, useMemo, useCallback } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import { partialRepay } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'
import {
  accountIdsFromBalanceOrder,
  debtWithPositionFallback,
  marginSnapshotForSymbol,
  sortByAccountOrder,
  type BorrowPositionLike,
} from '@/lib/borrowDashboardMetrics'

interface Row {
  accountId: number
  note: string
  free: number        // 现币
  borrowed: number    // 借币本金
  interest: number
  total: number       // 待还 = 本金 + 利息
  hasSnapshot: boolean
  debtSource: 'balance' | 'position' | 'none'
}

/**
 * 部分还币[指定] 弹窗(主界面暗色风格)。列出该币所有子账户的现币/借币,
 * 每行可自填还币数量单独还,或「一键全还」按本金+利息全额还清。
 */
export function PartialRepayDialog({ symbol, onClose, onDone, accountOrder = [], positions = [] }: {
  symbol: string
  onClose: () => void
  onDone?: () => void
  accountOrder?: number[]
  positions?: readonly BorrowPositionLike[]
}) {
  const balances = useBalanceStore((s) => s.balances)
  const markRepaid = useBalanceStore((s) => s.markRepaid)
  const addToast = useToastStore((s) => s.addToast)
  const base = symbol.replace('USDT', '')
  const [repaying, setRepaying] = useState<number | null>(null)        // 单账户还币中
  const [inputs, setInputs] = useState<Record<number, string>>({})    // 各账户输入的还币数量(币)
  const [amtInputs, setAmtInputs] = useState<Record<number, string>>({})  // 各账户输入的还币金额(USDT),与数量互斥
  const [bulkBusy, setBulkBusy] = useState(false)
  // 还币后暂停自动借币30分钟(默认不勾):不勾且挂单差为负 → 还完立即重借是设计行为(挂单开着=持续借)
  const [pauseBorrow, setPauseBorrow] = useState(false)

  // 该币所有子账户(全部展示,与图一致;有借币的可还)
  const rows: Row[] = useMemo(() => {
    const out: Row[] = []
    const positionNotes = new Map<number, string>()
    for (const position of positions) {
      const existing = positionNotes.get(position.sub_account_id)
      if (existing == null || (!existing && position.account_note)) {
        positionNotes.set(position.sub_account_id, position.account_note || existing || '')
      }
    }
    const accountIds = new Set<number>()
    for (const b of balances) {
      const sm = marginSnapshotForSymbol(b.symbol_margin, symbol)
      const free = sm?.free ?? 0
      const debt = debtWithPositionFallback(sm, positions, b.account_id, symbol)
      accountIds.add(b.account_id)
      out.push({
        accountId: b.account_id,
        note: b.note,
        free,
        borrowed: debt.principal,
        interest: debt.interest,
        total: debt.total,
        hasSnapshot: debt.hasSnapshot,
        debtSource: debt.source,
      })
    }
    // Include accounts represented only by a just-created active position.
    // Their balance snapshot may be delayed by one pusher cycle.
    for (const position of positions) {
      const accountId = position.sub_account_id
      if (accountIds.has(accountId)) continue
      const debt = debtWithPositionFallback(undefined, positions, accountId, symbol)
      if (debt.total <= 1e-8) continue
      out.push({
        accountId,
        note: positionNotes.get(accountId) || `#${accountId}`,
        free: 0,
        borrowed: debt.principal,
        interest: debt.interest,
        total: debt.total,
        hasSnapshot: false,
        debtSource: debt.source,
      })
      accountIds.add(accountId)
    }
    // Preserve the canonical creation rank across every symbol.  The balance
    // array is a correctly ordered fallback when the account API is pending.
    const stableAccountOrder = accountOrder.length > 0
      ? accountOrder
      : accountIdsFromBalanceOrder([
          ...balances,
          ...[...positionNotes.keys()]
            .filter((id) => !balances.some((balance) => balance.account_id === id))
            .map((account_id) => ({ account_id })),
        ])
    return sortByAccountOrder(out, stableAccountOrder, (row) => row.accountId)
  }, [accountOrder, balances, positions, symbol])

  // qty=按币数量还;usdt=按USDT金额还(后端以现价换算)。二者由输入框互斥保证只传其一。
  const doRepay = useCallback(async (r: Row, opts: { qty?: number; usdt?: number; repayAll?: boolean }) => {
    if (!opts.repayAll && (opts.qty ?? 0) <= 0 && (opts.usdt ?? 0) <= 0) { addToast('还币数量/金额需为正数', 'error'); return }
    setRepaying(r.accountId)
    try {
      const res = await partialRepay(
        r.accountId, symbol, opts.qty ?? 0, false, opts.usdt, pauseBorrow, opts.repayAll ?? false,
      )
      // 乐观递减用后端返回的实际还币量(金额换算/债务封顶后的真值),比前端输入更准
      const repaid = res.repaid ?? opts.qty ?? 0
      if (opts.repayAll && res.fully_repaid === true) markRepaid(r.accountId, symbol)
      else if (repaid > 0) markRepaid(r.accountId, symbol, repaid)
      addToast(
        `${r.note} ${res.message || `${base} 还币已提交`}`,
        opts.repayAll && res.fully_repaid !== true ? 'error' : 'success',
      )
      setInputs((p) => ({ ...p, [r.accountId]: '' }))
      setAmtInputs((p) => ({ ...p, [r.accountId]: '' }))
      onDone?.()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
      addToast(`${r.note} 还币失败: ${msg}`, 'error')
    }
    setRepaying(null)
  }, [symbol, base, markRepaid, addToast, onDone, pauseBorrow])

  // 一键全还(单账户):按本金+利息全额
  const repayAllOne = useCallback((r: Row) => {
    if (r.total <= 1e-8) { addToast(`${r.note} 无借币`, 'info'); return }
    doRepay(r, { repayAll: true })
  }, [doRepay, addToast])

  // 卖回现币残留(零债务行):平仓超买/尾批零头没有债务、还币闸不认,原先无任何操作入口。
  // 走 partial-repay 的 sell_residual 分支市价卖回 USDT;结果以后端 balance:refresh 推送对账。
  const sellResidual = useCallback(async (r: Row) => {
    setRepaying(r.accountId)
    try {
      const res = await partialRepay(r.accountId, symbol, r.free, true)
      addToast(`${r.note} ${(res as { message?: string })?.message || '卖回已提交'}`, 'success')
      onDone?.()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
      addToast(`${r.note} 卖回失败: ${msg}`, 'error')
    }
    setRepaying(null)
  }, [symbol, addToast, onDone])

  // 一键全还(所有账户):逐账户全额还
  const repayAllAccounts = useCallback(async () => {
    const need = rows.filter((r) => r.total > 1e-8)
    if (need.length === 0) { addToast('当前无借币可还', 'info'); return }
    setBulkBusy(true)
    let cleared = 0
    let incomplete = 0
    let failed = 0
    for (const r of need) {
      setRepaying(r.accountId)
      try {
        const res = await partialRepay(r.accountId, symbol, 0, false, undefined, pauseBorrow, true)
        if (res.fully_repaid === true) {
          markRepaid(r.accountId, symbol)
          cleared += 1
        } else {
          const repaid = res.repaid ?? 0
          if (repaid > 0) markRepaid(r.accountId, symbol, repaid)
          incomplete += 1
          addToast(`${r.note} ${res.message || '仍有剩余债务'}`, 'error')
        }
      } catch (e) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message
        addToast(`${r.note} 还币失败: ${msg}`, 'error')
        failed += 1
      }
    }
    setRepaying(null)
    setBulkBusy(false)
    if (incomplete === 0 && failed === 0) addToast(`已还清 ${cleared} 个子账户`, 'success')
    else addToast(`还清 ${cleared}，未清 ${incomplete}，失败 ${failed}`, 'error')
    onDone?.()
  }, [rows, symbol, markRepaid, addToast, onDone, pauseBorrow])

  const cellInput = 'w-20 bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-right text-foreground focus:outline-none focus:border-primary'

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2"
      onClick={(event) => {
        event.stopPropagation()
        if (!bulkBusy) onClose()
      }}
    >
      <div className="w-full max-w-[760px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-[#141420] shadow-2xl"
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
                <th className="px-2 py-1.5 text-right font-medium" title="Binance 杠杆户实时借币本金">本金</th>
                <th className="px-2 py-1.5 text-right font-medium" title="真实待还债务 = borrowed 本金 + interest">真实债务</th>
                <th className="px-2 py-1.5 text-center font-medium" title="按币数量还;与「还币金额」二选一,填一个另一个自动清空">还币数量</th>
                <th className="px-2 py-1.5 text-center font-medium" title="按USDT金额还:后端按现价换算成币数量;与「还币数量」二选一">还币金额(U)</th>
                <th className="px-2 py-1.5 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const hasDebt = r.total > 1e-8
                return (
                  <tr key={r.accountId} className="border-b border-border/30 hover:bg-accent/10">
                    <td className="px-2 py-1.5 font-medium whitespace-nowrap">{r.note}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground">{r.hasSnapshot ? (r.free > 1e-8 ? r.free.toFixed(4) : 0) : '-'}</td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-amber-400" title={r.debtSource === 'position' ? '余额快照尚未到达，暂按已确认持仓借币量估算；还币以 Binance 实时债务为准' : `本金 ${r.borrowed.toFixed(8)} + 利息 ${r.interest.toFixed(8)}`}>
                      {r.hasSnapshot ? (r.borrowed > 1e-8 ? r.borrowed.toFixed(4) : 0) : r.borrowed.toFixed(4)}
                      {r.debtSource === 'position' && <span className="ml-1 text-[9px] text-amber-300">估算</span>}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums">{hasDebt ? r.total.toFixed(4) : (r.hasSnapshot ? 0 : '-')}</td>
                    <td className="px-2 py-1.5 text-center">
                      <input
                        className={cellInput}
                        placeholder={hasDebt ? r.total.toFixed(2) : '0'}
                        value={inputs[r.accountId] ?? ''}
                        disabled={!hasDebt || bulkBusy}
                        onChange={(e) => {
                          const v = e.target.value
                          setInputs((p) => ({ ...p, [r.accountId]: v }))
                          if (v.trim() !== '') setAmtInputs((p) => ({ ...p, [r.accountId]: '' }))  // 与金额互斥
                        }}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      <input
                        className={cellInput}
                        placeholder={hasDebt ? 'USDT' : '0'}
                        title="按USDT金额还币,后端按现价换算成数量"
                        value={amtInputs[r.accountId] ?? ''}
                        disabled={!hasDebt || bulkBusy}
                        onChange={(e) => {
                          const v = e.target.value
                          setAmtInputs((p) => ({ ...p, [r.accountId]: v }))
                          if (v.trim() !== '') setInputs((p) => ({ ...p, [r.accountId]: '' }))  // 与数量互斥
                        }}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-center whitespace-nowrap">
                      <button
                        onClick={() => {
                          const rawQty = (inputs[r.accountId] ?? '').trim()
                          const rawAmt = (amtInputs[r.accountId] ?? '').trim()
                          if (rawQty !== '') {           // 数量框有值 → 按数量还
                            const v = parseFloat(rawQty)
                            if (isNaN(v) || v <= 0) { addToast('还币数量需为正数', 'error'); return }
                            if (r.hasSnapshot && v > r.total + 1e-8) {   // 快照真值存在时才在前端封顶;估算行交由后端权威校验
                              addToast(`${r.note} 还币数量 ${v} 超过待还 ${r.total.toFixed(4)} ${base},请重新输入`, 'error')
                              return
                            }
                            doRepay(r, { qty: v })
                            return
                          }
                          if (rawAmt !== '') {           // 金额框有值 → 按USDT金额还(后端换算,超债自动封顶)
                            const v = parseFloat(rawAmt)
                            if (isNaN(v) || v <= 0) { addToast('还币金额需为正数', 'error'); return }
                            doRepay(r, { usdt: v })
                            return
                          }
                          doRepay(r, { repayAll: true })   // 两框都留空=交由服务端按 Binance 实际债务全额还
                        }}
                        disabled={!hasDebt || repaying === r.accountId || bulkBusy}
                         title={hasDebt ? (r.debtSource === 'position' ? '当前为已确认持仓临时估算；提交后由服务端按 Binance 实时债务核对' : undefined) : '无借币,无需还币;现币残留用「卖回」清理'}
                        className="px-2 py-0.5 rounded text-[10px] bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-40 mr-1"
                      >{repaying === r.accountId ? '还币中' : '还币'}</button>
                      <button
                        onClick={() => repayAllOne(r)}
                        disabled={!hasDebt || repaying === r.accountId || bulkBusy}
                        className="px-2 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 disabled:opacity-40"
                      >一键全还</button>
                      {!hasDebt && r.free > 1e-8 && (
                        <button
                          onClick={() => sellResidual(r)}
                          disabled={repaying === r.accountId || bulkBusy}
                          title="无债务但杠杆户仍有现币残留(平仓超买/尾批零头),市价卖回 USDT"
                          className="ml-1 px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-40"
                        >{repaying === r.accountId ? '卖回中' : '卖回'}</button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">无子账户</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <label className="mr-auto flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none"
            title="不勾:还完立即恢复自动借币(挂单差为负会秒级重借,持续囤券语义)。勾选:暂停30分钟,状态列显示「还币暂停」可点击提前解除">
            <input type="checkbox" checked={pauseBorrow} onChange={(e) => setPauseBorrow(e.target.checked)} className="accent-amber-500" />
            还币后暂停该币自动借币 30 分钟
          </label>
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
