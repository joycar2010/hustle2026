import { useEffect, useState, useCallback } from 'react'
import { useEngineStore } from '@/stores/engineStore'
import { useSpreadStore } from '@/stores/spreadStore'
import { OwlTreeTable, type Position, type SymbolRuleInfo } from '@/components/dashboard/OwlTreeTable'
import { EngineHealthBar } from '@/components/dashboard/EngineHealthBar'
import { TransferDialog } from '@/components/dashboard/TransferDialog'
import { SymbolRuleDialog } from '@/components/dashboard/SymbolRuleDialog'
import { RemoveSymbolDialog } from '@/components/dashboard/RemoveSymbolDialog'
import { PartialRepayDialog } from '@/components/dashboard/PartialRepayDialog'
import { ManualOpenDialog } from '@/components/dashboard/ManualOpenDialog'
import { ViewDetailDialog } from '@/components/dashboard/ViewDetailDialog'
import { getPositions, getPushedSymbols, removePushedSymbol, pushSymbol, manualClose, manualHedge, manualRepay, getEngineHealth, listTailPositions, cleanupTailPositions, getMaxBorrowable, startAllWorkers } from '@/api/engine'
import { getSubAccounts, clearSubAccount } from '@/api/accounts'
import { getSpreads } from '@/api/spreads'
import { addToBlacklist, getSymbolRules } from '@/api/rules'
import { getCoins } from '@/api/coins'
import { confirmDialog } from '@/components/ui/confirm'
import { useToastStore } from '@/components/ui/toast'
import type { SpreadData } from '@/stores/spreadStore'

interface SubAccount {
  id: number
  note: string
}

export function DashboardPage() {
  const fetchDashboard = useEngineStore((s) => s.fetchDashboard)
  const addToast = useToastStore((s) => s.addToast)
  const setBulk = useSpreadStore((s) => s.setBulk)
  const [positions, setPositions] = useState<Position[]>([])
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [pushedSymbols, setPushedSymbols] = useState<string[]>([])
  const [pushedAt, setPushedAt] = useState<Record<string, number>>({})
  const [showTransfer, setShowTransfer] = useState(false)
  const [transferAccountId, setTransferAccountId] = useState<number | undefined>()
  const [ruleSymbol, setRuleSymbol] = useState<string | null>(null)
  const [ruleAccountId, setRuleAccountId] = useState<number | undefined>()
  const [removeSymbol, setRemoveSymbol] = useState<string | null>(null)
  const [repaySymbol, setRepaySymbol] = useState<string | null>(null)
  const [openSymbol, setOpenSymbol] = useState<string | null>(null)            // 手动开仓弹窗
  const [detailPosition, setDetailPosition] = useState<Position | null>(null)  // 查看详情弹窗
  const [symbolRulesMap, setSymbolRulesMap] = useState<Map<string, SymbolRuleInfo>>(new Map())
  const [delistingSymbols, setDelistingSymbols] = useState<Set<string>>(new Set())
  const [riskySymbols, setRiskySymbols] = useState<Set<string>>(new Set())
  const [accountRates, setAccountRates] = useState<Record<string, number>>({})

  useEffect(() => {
    // [第三梯队] 轮询用 AbortController:慢网下撤销上一次未完成的 health 请求,避免堆叠
    let ctrl: AbortController | null = null
    const fetchThrottle = () => {
      ctrl?.abort()
      ctrl = new AbortController()
      getEngineHealth(ctrl.signal).then((h) => {
        setAccountRates(h.account_borrow_rates ?? {})
      }).catch(() => {})
    }
    fetchThrottle()
    const t = setInterval(fetchThrottle, 15000)
    return () => { clearInterval(t); ctrl?.abort() }
  }, [])

  const refreshPositions = useCallback((signal?: AbortSignal) => {
    getPositions('ACTIVE', signal).then(setPositions).catch(() => {})
  }, [])

  const refreshPushed = useCallback(() => {
    getPushedSymbols().then((d) => { setPushedSymbols(d.pushed_symbols || []); setPushedAt(d.pushed_at || {}) }).catch(() => {})
  }, [])

  const refreshSymbolRules = useCallback(() => {
    getSymbolRules(500).then((data: { items?: Array<{ symbol: string; allow_remove: boolean; allow_repay: boolean; open_spread: number | null; close_spread: number | null; order_amount: number | null; close_funding_ratio: number | null; source: string }> }) => {
      const m = new Map<string, SymbolRuleInfo>()
      for (const r of data.items || []) {
        m.set(r.symbol, {
          allow_remove: r.allow_remove ?? true,
          allow_repay: r.allow_repay ?? true,
          open_spread: r.open_spread,
          close_spread: r.close_spread,
          order_amount: r.order_amount,
          close_funding_ratio: r.close_funding_ratio ?? null,
          source: r.source || 'global',
        })
      }
      setSymbolRulesMap(m)
    }).catch(() => {})
  }, [])

  const refreshDelistingCoins = useCallback(() => {
    getCoins({ is_delisting: 'true' }).then((coins) => {
      setDelistingSymbols(new Set(coins.map((c) => c.symbol)))
    }).catch(() => {})
  }, [])

  const refreshRiskySymbols = useCallback(() => {
    // 风险币种统一以 coins 表(is_risky,经币管页维护)为唯一源,替代已下线的 /api/symbols/risky
    getCoins({ is_risky: 'true' }).then((coins) => {
      setRiskySymbols(new Set(coins.filter((c) => c.is_risky).map((c) => c.symbol)))
    }).catch(() => {})
  }, [])

  // Initial data load — WebSocket handles live updates (实时主通道)
  useEffect(() => {
    fetchDashboard()
    getSpreads().then((data: SpreadData[]) => setBulk(data)).catch(() => {})
    getSubAccounts(true).then(setAccounts).catch(() => {})
    refreshPositions()
    refreshPushed()
    refreshSymbolRules()
    refreshDelistingCoins()
    refreshRiskySymbols()
  }, [fetchDashboard, setBulk, refreshPositions, refreshPushed, refreshSymbolRules, refreshDelistingCoins, refreshRiskySymbols])

  // [修3] 低频 REST 兜底轮询:WS 假死/断连时业务数据仍每 30s 刷新,不再整页冻结。
  // WS 正常时这只是用同源快照覆盖(无副作用);同时每 30s 的 API 调用顺带保活 token 续期。
  useEffect(() => {
    // [第三梯队] 30s 兜底轮询同样接入 AbortController:慢网下新一轮开始前先撤销上一轮在途的 positions/spreads,释放带宽
    let ctrl: AbortController | null = null
    const t = setInterval(() => {
      ctrl?.abort()
      ctrl = new AbortController()
      const sig = ctrl.signal
      fetchDashboard()
      refreshPositions(sig)
      getSpreads(sig).then((data: SpreadData[]) => setBulk(data)).catch(() => {})
    }, 30000)
    return () => { clearInterval(t); ctrl?.abort() }
  }, [fetchDashboard, refreshPositions, setBulk])

  // Refresh pushed symbols on push events
  useEffect(() => {
    const handleOpenRule = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.symbol) setRuleSymbol(detail.symbol)
    }
    window.addEventListener('open:symbol-rule', handleOpenRule)
    window.addEventListener('pushed:refresh', refreshPushed)
    return () => {
      window.removeEventListener('open:symbol-rule', handleOpenRule)
      window.removeEventListener('pushed:refresh', refreshPushed)
    }
  }, [refreshPushed])

  // WebSocket position updates
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (!detail) return
      setPositions((prev) => {
        const idx = prev.findIndex((p) => p.id === detail.id)
        if (idx >= 0) {
          const updated = [...prev]
          updated[idx] = { ...updated[idx], ...detail }
          // drop only on terminal states; keep OPEN/BORROWED_IDLE/PENDING_REPAY
          if (detail.status === 'CLOSED' || detail.status === 'FAILED') return updated.filter(p => p.id !== detail.id)
          return updated
        }
        if (['OPEN', 'BORROWED_IDLE', 'PENDING_REPAY'].includes(detail.status)) return [detail, ...prev]
        return prev
      })
    }
    window.addEventListener('ws:position', handler)
    return () => window.removeEventListener('ws:position', handler)
  }, [])

  const handleAction = useCallback(async (action: string, symbol: string, position?: Position, extra?: Record<string, unknown>) => {
    switch (action) {
      case 'transfer':
        setTransferAccountId(position?.sub_account_id)
        setShowTransfer(true)
        break
      case 'blacklist':
        if (await confirmDialog({ title: '加入黑名单', message: `确认将 "${symbol}" 加入黑名单？\n加入后从借币列表移除，不再推送。`, danger: true })) {
          addToBlacklist(symbol).then(() => refreshPushed()).catch(() => {})
        }
        break
      case 'set_rule':
        setRuleSymbol(symbol)
        setRuleAccountId(extra?.initialAccountId as number | undefined)
        break
      case 'push_symbol':
        pushSymbol(symbol).then(() => refreshPushed()).catch(() => {})
        break
      case 'remove_slot': {
        const hasOpenPos = positions.some(p => p.symbol === symbol && p.status === 'OPEN')
        if (hasOpenPos) {
          addToast(`无法移除 ${symbol}：仍有子账户持仓中。请先平仓所有持仓后再移除。`, 'error')
          break
        }
        // 主界面风格弹窗:列出各子账户现币/借币 → 确认后逐账户自动还币 → 再移除
        setRemoveSymbol(symbol)
        break
      }
      case 'resume_slot':
        // "停止挂单"是顶栏的全局引擎停;"恢复下单"应对称地重启引擎,而非重推一个已在列表的币(否则无反应)
        startAllWorkers()
          .then(() => addToast('已恢复下单（引擎已启动）', 'success'))
          .catch((e) => addToast(`恢复下单失败: ${e.response?.data?.detail || e.message}`, 'error'))
        break
      case 'batch_remove': {
        const noPos = pushedSymbols.filter(
          s => !positions.some(p => p.symbol === s && p.status === 'OPEN')
        )
        if (noPos.length === 0) {
          addToast('没有无持仓的推送币种', 'info')
          return
        }
        if (await confirmDialog({ title: '批量移除', message: `批量移除 ${noPos.length} 个无持仓币种？\n${noPos.join(', ')}` })) {
          Promise.all(noPos.map(s => removePushedSymbol(s))).then(() => refreshPushed()).catch(() => {})
        }
        break
      }
      case 'manual_open':
        // 主界面风格弹窗:点子账户按规则开仓 / 一键全开(替代原 prompt 输序号+金额)
        setOpenSymbol(symbol)
        break
      case 'force_close':
        if (position) {
          if (!(await confirmDialog({ title: '强制平仓', message: `确认强制平仓 ${symbol} #${position.id}？\n账户: ${position.account_note || '#' + position.sub_account_id}\n将立即市价平仓+买回+还币。`, danger: true }))) break
          manualClose(position.id)
            .then((r) => { addToast(`${r.message}　盈亏: ${r.realized_pnl}`, 'success'); refreshPositions() })
            .catch((e) => addToast(`平仓失败: ${e.response?.data?.detail || e.message}`, 'error'))
        }
        break
      case 'manual_hedge':
        if (position) {
          if (!(await confirmDialog({ title: '手动对冲', message: `确认手动对冲 ${symbol} #${position.id}？\n将卖出借来的现货(做空)+合约市价跟多。` }))) break
          manualHedge(position.id)
            .then((r) => { addToast(r.message || '对冲完成', 'success'); refreshPositions() })
            .catch((e) => addToast(`对冲失败: ${e.response?.data?.detail || e.message}`, 'error'))
        }
        break
      case 'manual_repay':
        if (position) {
          if (!(await confirmDialog({ title: '手动还币', message: `确认手动还币 ${symbol} #${position.id}？\n将买回的现币还清杠杆负债，持仓结算平仓。`, danger: true }))) break
          manualRepay(position.id)
            .then((r) => { addToast(`${r.message}　盈亏: ${r.realized_pnl ?? '-'}`, 'success'); refreshPositions() })
            .catch((e) => addToast(`还币失败: ${e.response?.data?.detail || e.message}`, 'error'))
        }
        break
      case 'partial_repay': {
        // 弹出主界面风格弹窗:列该币所有子账户现币/借币,可逐账户自填还币或一键全还
        setRepaySymbol(symbol)
        break
      }
      case 'clear_account': {
        const clearSubId = extra?.subAccountId as number | undefined
        if (!clearSubId) break
        // 确认=禁用并平仓(高危),取消则不操作;仅禁用走账户页。简化为单一高危确认。
        if (!(await confirmDialog({
          title: '清除账户',
          message: `确认禁用并平仓账户 #${clearSubId}？\n将禁用该子账户并市价平掉其全部持仓。`,
          confirmText: '禁用并平仓', danger: true,
        }))) break
        const mode = 'disable_and_close' as const
        clearSubAccount(clearSubId, mode)
          .then(() => { addToast('操作成功', 'success'); refreshPositions() })
          .catch((e: unknown) => {
            const resp = (e as { response?: { data?: { detail?: string } } })?.response
            addToast(`操作失败: ${resp?.data?.detail || (e as Error)?.message || '未知错误'}`, 'error')
          })
        break
      }
      case 'view_detail':
        // 主界面风格弹窗(替代纯 toast);伪行展示该账户余额/借币/可借而非空 position 字段
        if (position) setDetailPosition(position)
        break
      case 'cleanup_tail': {
        const maxStr = prompt('清理尾仓:平掉名义价值 ≤ N USDT 的碎仓\n输入阈值 (默认 10):', '10')
        if (maxStr === null) break
        const maxU = maxStr.trim() ? parseFloat(maxStr) : 10
        if (isNaN(maxU) || maxU <= 0) { addToast('请输入有效阈值', 'error'); break }
        listTailPositions(maxU)
          .then(async (tails) => {
            if (!tails.length) { addToast(`无 ≤ ${maxU}U 的尾仓`, 'info'); return }
            const list = tails.map((t) => `${t.symbol} #${t.id}  ${parseFloat(t.open_usdt_amount).toFixed(1)}U`).join('\n')
            if (!(await confirmDialog({ title: '清理尾仓', message: `发现 ${tails.length} 个尾仓 (≤${maxU}U),将逐个市价平仓+买回+还币:\n\n${list}\n\n确认清理?`, danger: true }))) return
            cleanupTailPositions(maxU)
              .then((r: { message?: string; closed?: number; errors?: string[] }) => {
                addToast(`${r.message || '清理完成'}${r.errors && r.errors.length ? ' (含错误)' : ''}`, r.errors && r.errors.length ? 'error' : 'success')
                refreshPositions()
              })
              .catch((e) => addToast(`清理失败: ${e.response?.data?.detail || e.message}`, 'error'))
          })
          .catch((e) => addToast(`查询尾仓失败: ${e.response?.data?.detail || e.message}`, 'error'))
        break
      }
      case 'refresh_borrowable': {
        const subId = (extra?.subAccountId as number | undefined) ?? position?.sub_account_id
        if (!subId) break
        getMaxBorrowable(subId, symbol)
          .then((d: { max_borrowable?: string; borrow_limit?: string; asset?: string }) => addToast(
            `${d.asset || symbol} @ 账户#${subId} 可借: ${d.max_borrowable ?? '-'}${d.borrow_limit ? `（VIP上限 ${d.borrow_limit}）` : ''}`,
            'info'))
          .catch((e) => addToast(`查询失败: ${e.response?.data?.detail || e.message}`, 'error'))
        break
      }
      default:
        break
    }
  }, [pushedSymbols, positions, accounts, refreshPushed, refreshPositions])

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {riskySymbols.size > 0 && (
        <div className="bg-red-500/10 border-b border-red-500/20 overflow-hidden shrink-0">
          <div className="animate-marquee whitespace-nowrap py-1 text-[11px] text-red-500 font-medium">
            &#9888; 风险币种警告: {[...riskySymbols].join(', ')} — 请注意仓位风险管理 &#9888;
          </div>
        </div>
      )}
      <EngineHealthBar />
      <OwlTreeTable
        positions={positions}
        pushedSymbols={pushedSymbols}
        pushedAt={pushedAt}
        symbolRules={symbolRulesMap}
        delistingSymbols={delistingSymbols}
        riskySymbols={riskySymbols}
        accountRates={accountRates}
        onAction={handleAction}
      />
      {showTransfer && (
        <TransferDialog
          accounts={accounts}
          defaultAccountId={transferAccountId}
          onClose={() => setShowTransfer(false)}
        />
      )}
      {ruleSymbol && (
        <SymbolRuleDialog
          symbol={ruleSymbol}
          initialAccountId={ruleAccountId}
          onClose={() => { setRuleSymbol(null); setRuleAccountId(undefined); refreshSymbolRules() }}
        />
      )}
      {removeSymbol && (
        <RemoveSymbolDialog
          symbol={removeSymbol}
          onClose={() => setRemoveSymbol(null)}
          onRemoved={() => { refreshPushed(); refreshPositions() }}
        />
      )}
      {repaySymbol && (
        <PartialRepayDialog
          symbol={repaySymbol}
          onClose={() => setRepaySymbol(null)}
          onDone={() => refreshPositions()}
        />
      )}
      {openSymbol && (
        <ManualOpenDialog
          symbol={openSymbol}
          onClose={() => setOpenSymbol(null)}
          onDone={() => refreshPositions()}
        />
      )}
      {detailPosition && (
        <ViewDetailDialog
          position={detailPosition}
          onClose={() => setDetailPosition(null)}
        />
      )}
    </div>
  )
}
