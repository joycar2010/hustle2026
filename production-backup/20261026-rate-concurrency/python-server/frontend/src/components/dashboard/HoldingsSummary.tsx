import { useState, useMemo, useCallback } from 'react'
import { useBalanceStore } from '@/stores/balanceStore'
import { partialRepay } from '@/api/engine'
import { confirmDialog } from '@/components/ui/confirm'
import { useToastStore } from '@/components/ui/toast'
import {
  accountIdsFromBalanceOrder,
  debtWithPositionFallback,
  sortByAccountOrder,
  type BorrowPositionLike,
} from '@/lib/borrowDashboardMetrics'
import { PartialRepayDialog } from './PartialRepayDialog'

interface HeldRow {
  accountId: number
  note: string
  symbol: string
  base: string
  free: number        // 现币:当前手上可用现币(实时)
  borrowed: number    // 借币:杠杆户实时借币本金
  interest: number
  total: number
  hasSnapshot: boolean
  debtSource: 'balance' | 'position' | 'none'
}

/** 全局持币汇总:列出所有子账户当前借了哪些币、多少,逐行单独还币。数据来自 balance 实时快照。 */
export function HoldingsSummary({
  onClose,
  accountOrder = [],
  positions = [],
}: {
  onClose: () => void
  accountOrder?: number[]
  positions?: readonly BorrowPositionLike[]
}) {
  const balances = useBalanceStore((s) => s.balances)
  const markRepaid = useBalanceStore((s) => s.markRepaid)
  const addToast = useToastStore((s) => s.addToast)
  const [repaying, setRepaying] = useState<string | null>(null)
  const [partialSymbol, setPartialSymbol] = useState<string | null>(null)
  // 还币后暂停自动借币30分钟(默认不勾=还完立即恢复借币,挂单负阈会秒级重借,持续囤券语义)
  const [pauseBorrow, setPauseBorrow] = useState(false)

  const { rows, residuals } = useMemo(() => {
    const out: HeldRow[] = []
    const res: HeldRow[] = []
    const positionAccounts = new Map<number, string>()
    for (const position of positions) {
      const existing = positionAccounts.get(position.sub_account_id)
      if (existing == null || (!existing && position.account_note)) {
        positionAccounts.set(position.sub_account_id, position.account_note || existing || '')
      }
    }
    const rowsByKey = new Set<string>()
    for (const b of balances) {
      const sm = b.symbol_margin || {}
      for (const [symbol, m] of Object.entries(sm)) {
        const debt = debtWithPositionFallback(m, positions, b.account_id, symbol)
        const borrowed = debt.principal
        const interest = debt.interest
        const free = m.free ?? 0
        const row: HeldRow = {
          accountId: b.account_id, note: b.note, symbol,
          base: symbol.replace('USDT', ''),
          free, borrowed, interest, total: borrowed + interest,
          hasSnapshot: debt.hasSnapshot,
          debtSource: debt.source,
        }
        rowsByKey.add(`${b.account_id}:${String(symbol).toUpperCase()}`)
        if (borrowed + interest > 1e-8) out.push(row)
        // 零债务现币残留(含未推送币,后端 residual_only 通道):历史超买零头/遗留现货,
        // 不在交易对列表上完全不可见 → 在此提供唯一的"看见+卖回"入口
        else if (free > 1e-8) res.push(row)
      }
    }
    // A borrow position can arrive one WS cycle before its Binance balance
    // snapshot. Include it so the dashboard never renders a false zero.
    for (const position of positions) {
      const normalizedSymbol = String(position.symbol || '').toUpperCase()
      const key = `${position.sub_account_id}:${normalizedSymbol}`
      if (!normalizedSymbol || rowsByKey.has(key)) continue
      const debt = debtWithPositionFallback(undefined, positions, position.sub_account_id, normalizedSymbol)
      if (debt.total <= 1e-8) continue
      out.push({
        accountId: position.sub_account_id,
        note: positionAccounts.get(position.sub_account_id) || `#${position.sub_account_id}`,
        symbol: normalizedSymbol,
        base: normalizedSymbol.replace('USDT', ''),
        free: 0,
        borrowed: debt.principal,
        interest: debt.interest,
        total: debt.total,
        hasSnapshot: false,
        debtSource: debt.source,
      })
      rowsByKey.add(key)
    }
    // The balance stream is already serialized in creation order by the
    // pusher.  Prefer the explicit API rank when available; never reorder by
    // debt amount or numeric account id.
    const stableAccountOrder = accountOrder.length > 0
      ? accountOrder
      : accountIdsFromBalanceOrder([
          ...balances,
          ...[...positionAccounts.keys()]
            .filter((id) => !balances.some((balance) => balance.account_id === id))
            .map((account_id) => ({ account_id })),
        ])
    return {
      rows: sortByAccountOrder(out, stableAccountOrder, (row) => row.accountId),
      residuals: sortByAccountOrder(res, stableAccountOrder, (row) => row.accountId),
    }
  }, [accountOrder, balances, positions])

  const handleRepay = useCallback(async (r: HeldRow) => {
    if (!(await confirmDialog({
      title: '还币',
      message: `确认为 ${r.note} 还清 ${r.base}？\n本金 ${r.borrowed.toFixed(6)} + 利息 ${r.interest.toFixed(6)} ≈ ${r.total.toFixed(6)} ${r.base}\n债务确认归零后将自动卖回或处理该币现币残留。${r.debtSource === 'position' ? '\n（余额快照尚未到达，数量为已确认持仓临时估算；服务端将再次核对）' : ''}`,
      danger: true,
    }))) return
    const key = `${r.accountId}-${r.symbol}`
    setRepaying(key)
    try {
      // ``sellResidual=true`` is explicit operator consent from the holdings
      // modal. The backend still waits for authoritative zero debt before it
      // touches any remaining free asset.
      const res = await partialRepay(r.accountId, r.symbol, 0, true, undefined, pauseBorrow, true)
      if (res.fully_repaid === true) {
        markRepaid(r.accountId, r.symbol)
        addToast(
          res.cleanup_warning
            ? `${r.note} ${r.base} 债务已还清；${res.cleanup_warning}`
            : `${r.note} ${res.message || `${r.base} 已全部还清并完成残留处理`}`,
          res.cleanup_warning ? 'error' : 'success',
        )
      } else {
        const repaid = res.repaid ?? 0
        if (repaid > 0) markRepaid(r.accountId, r.symbol, repaid)
        addToast(res.message || `${r.note} ${r.base} 尚有剩余债务`, 'error')
      }
    } catch (e) {
      addToast(`还币失败: ${(e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message}`, 'error')
    }
    setRepaying(null)
  }, [addToast, markRepaid, pauseBorrow])

  // 卖回零债务现币残留:≥5U 市价卖回；<5U 安全留在杠杆账户，不调用资产级 dust 转换。
  const handleSellResidual = useCallback(async (r: HeldRow) => {
    if (!(await confirmDialog({
      title: '卖回残留',
      message: `确认把 ${r.note} 的 ${r.free.toFixed(6)} ${r.base}(无债务残留)市价卖回 USDT？`,
      danger: true,
    }))) return
    const key = `${r.accountId}-${r.symbol}`
    setRepaying(key)
    try {
      const res = await partialRepay(r.accountId, r.symbol, r.free, true)
      addToast(`${r.note} ${(res as { message?: string })?.message || '卖回已提交'}`, 'success')
    } catch (e) {
      addToast(`卖回失败: ${(e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message}`, 'error')
    }
    setRepaying(null)
  }, [addToast])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2" onClick={onClose}>
      <div className="w-full max-w-[720px] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-background shadow-2xl"
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
                <th className="px-3 py-1.5 text-right font-medium" title="真实待还债务 = Binance borrowed 本金 + interest">真实债务</th>
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
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-amber-400">
                      {r.borrowed.toFixed(6)}
                      {r.debtSource === 'position' && <span className="ml-1 text-[9px] text-amber-300" title="余额快照尚未到达，暂按已确认持仓借币量估算；还币以 Binance 实时债务为准">估算</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-muted-foreground">{r.interest.toFixed(6)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums">{r.total.toFixed(6)}</td>
                    <td className="px-3 py-1.5 text-center whitespace-nowrap">
                      <button
                        onClick={() => setPartialSymbol(r.symbol)}
                        disabled={repaying === key}
                        className="mr-1 px-2 py-0.5 rounded text-[10px] bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-40"
                      >部分还</button>
                      <button
                        onClick={() => handleRepay(r)}
                        disabled={repaying === key}
                        className="px-2 py-0.5 rounded text-[10px] bg-negative/20 text-negative hover:bg-negative/30 disabled:opacity-40"
                      >{repaying === key ? '还币中' : '全部还'}</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {residuals.length > 0 && (
          <div className="border-t border-border">
            <div className="px-4 py-2 bg-[#0d0d14] text-[11px] font-semibold">
              现币残留(无债务) <span className="text-muted-foreground font-normal">共 {residuals.length} 笔 — 历史超买零头/遗留现货。名义 ≥5U 可卖回 USDT；&lt;5U 保留在杠杆账户，不会自动转 BNB，以免连带处理现货钱包原有同币。</span>
            </div>
            <table className="w-full text-[11px] border-collapse">
              <tbody>
                {residuals.map((r) => {
                  const key = `${r.accountId}-${r.symbol}`
                  return (
                    <tr key={key} className="border-b border-border/30 hover:bg-[#1a1a22]/60">
                      <td className="px-3 py-1.5 font-medium">{r.note}</td>
                      <td className="px-3 py-1.5">{r.base}</td>
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums text-foreground">{r.free.toFixed(6)}</td>
                      <td className="px-3 py-1.5 text-center w-24">
                        <button
                          onClick={() => handleSellResidual(r)}
                          disabled={repaying === key}
                          className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-40"
                        >{repaying === key ? '卖回中' : '卖回'}</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center px-3 py-2 border-t border-border/50">
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none"
            title="不勾:还完立即恢复自动借币(挂单差为负会秒级重借)。勾选:暂停30分钟,状态列「还币暂停」可点击提前解除">
            <input type="checkbox" checked={pauseBorrow} onChange={(e) => setPauseBorrow(e.target.checked)} className="accent-amber-500" />
            还币后暂停该币自动借币 30 分钟
          </label>
        </div>
        <p className="text-[10px] text-muted-foreground/50 px-3 py-2">
          数据来自引擎实时余额快照(杠杆账户已借本金 + 已计利息);若快照尚未到达，标记“估算”的行暂按已确认持仓借币量显示，服务端还币前会重新核对真实债务。还币后约数秒刷新。
          残留区名义价值低于币安最小卖出额(约5U)时会安全留在杠杆账户，不会自动划转或兑换 BNB。
        </p>
      </div>
      {partialSymbol && (
        <PartialRepayDialog
          symbol={partialSymbol}
          accountOrder={accountOrder}
          positions={positions}
          onClose={() => setPartialSymbol(null)}
        />
      )}
    </div>
  )
}
