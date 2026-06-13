import { useEffect, useState, useCallback } from 'react'
import { useEngineStore } from '@/stores/engineStore'
import { useSpreadStore } from '@/stores/spreadStore'
import { OwlTreeTable, type Position, type SymbolRuleInfo } from '@/components/dashboard/OwlTreeTable'
import { EngineHealthBar } from '@/components/dashboard/EngineHealthBar'
import { TransferDialog } from '@/components/dashboard/TransferDialog'
import { SymbolRuleDialog } from '@/components/dashboard/SymbolRuleDialog'
import { getPositions, getPushedSymbols, removePushedSymbol, pushSymbol, partialRepay, manualOpen, manualClose, manualHedge, manualRepay, getEngineHealth, listTailPositions, cleanupTailPositions, getMaxBorrowable } from '@/api/engine'
import { getSubAccounts, clearSubAccount } from '@/api/accounts'
import { getSpreads } from '@/api/spreads'
import { addToBlacklist, getSymbolRules } from '@/api/rules'
import { getCoins } from '@/api/coins'
import { getRiskySymbols } from '@/api/symbols'
import type { SpreadData } from '@/stores/spreadStore'

interface SubAccount {
  id: number
  note: string
}

export function DashboardPage() {
  const fetchDashboard = useEngineStore((s) => s.fetchDashboard)
  const setBulk = useSpreadStore((s) => s.setBulk)
  const [positions, setPositions] = useState<Position[]>([])
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [pushedSymbols, setPushedSymbols] = useState<string[]>([])
  const [showTransfer, setShowTransfer] = useState(false)
  const [transferAccountId, setTransferAccountId] = useState<number | undefined>()
  const [ruleSymbol, setRuleSymbol] = useState<string | null>(null)
  const [ruleAccountId, setRuleAccountId] = useState<number | undefined>()
  const [symbolRulesMap, setSymbolRulesMap] = useState<Map<string, SymbolRuleInfo>>(new Map())
  const [delistingSymbols, setDelistingSymbols] = useState<Set<string>>(new Set())
  const [riskySymbols, setRiskySymbols] = useState<Set<string>>(new Set())
  const [throttleRate, setThrottleRate] = useState(0)

  useEffect(() => {
    const fetchThrottle = () => getEngineHealth().then((h) => setThrottleRate(h.throttle_rate ?? 0)).catch(() => {})
    fetchThrottle()
    const t = setInterval(fetchThrottle, 15000)
    return () => clearInterval(t)
  }, [])

  const refreshPositions = useCallback(() => {
    getPositions('ACTIVE').then(setPositions).catch(() => {})
  }, [])

  const refreshPushed = useCallback(() => {
    getPushedSymbols().then((d) => setPushedSymbols(d.pushed_symbols || [])).catch(() => {})
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
    getRiskySymbols().then((syms) => {
      setRiskySymbols(new Set(syms))
    }).catch(() => {})
  }, [])

  // Initial data load — no polling, WebSocket handles live updates
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

  const handleAction = useCallback((action: string, symbol: string, position?: Position, extra?: Record<string, unknown>) => {
    switch (action) {
      case 'transfer':
        setTransferAccountId(position?.sub_account_id)
        setShowTransfer(true)
        break
      case 'blacklist':
        if (confirm(`确认将 "${symbol}" 加入黑名单？加入后从借币列表移除，不再推送。`)) {
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
          alert(`无法移除 ${symbol}：仍有子账户持仓中。请先平仓所有持仓后再移除。`)
          break
        }
        if (confirm(`确认移除 ${symbol}？`)) {
          removePushedSymbol(symbol).then(() => refreshPushed()).catch(() => {})
        }
        break
      }
      case 'resume_slot':
        pushSymbol(symbol).then(() => refreshPushed()).catch(() => {})
        break
      case 'batch_remove': {
        const noPos = pushedSymbols.filter(
          s => !positions.some(p => p.symbol === s && p.status === 'OPEN')
        )
        if (noPos.length === 0) {
          alert('没有无持仓的推送币种')
          return
        }
        if (confirm(`批量移除 ${noPos.length} 个无持仓币种？\n${noPos.join(', ')}`)) {
          Promise.all(noPos.map(s => removePushedSymbol(s))).then(() => refreshPushed()).catch(() => {})
        }
        break
      }
      case 'manual_open': {
        if (accounts.length === 0) { alert('无可用子账户'); break }
        let accId = accounts[0].id
        if (accounts.length > 1) {
          const list = accounts.map((a, i) => `${i + 1}. ${a.note} (#${a.id})`).join('\n')
          const pick = prompt(`手动开仓 ${symbol}\n选择账户:\n${list}\n\n输入序号:`)
          if (!pick) break
          const idx = parseInt(pick, 10) - 1
          if (isNaN(idx) || idx < 0 || idx >= accounts.length) { alert('无效序号'); break }
          accId = accounts[idx].id
        }
        const amtStr = prompt(`手动开仓 ${symbol} @ 账户#${accId}\n下单金额(USDT, 留空用全局规则):`)
        if (amtStr === null) break
        const amt = amtStr.trim() ? parseFloat(amtStr) : undefined
        if (amtStr.trim() && (isNaN(amt as number) || (amt as number) <= 0)) { alert('请输入有效金额'); break }
        manualOpen(accId, symbol, amt)
          .then((r) => { alert(r.message || '开仓已提交'); refreshPositions() })
          .catch((e) => alert(`开仓失败: ${e.response?.data?.detail || e.message}`))
        break
      }
      case 'force_close':
        if (position) {
          if (!confirm(`确认强制平仓 ${symbol} #${position.id}？\n账户: ${position.account_note || '#' + position.sub_account_id}\n将立即市价平仓+买回+还币。`)) break
          manualClose(position.id)
            .then((r) => { alert(`${r.message}　盈亏: ${r.realized_pnl}`); refreshPositions() })
            .catch((e) => alert(`平仓失败: ${e.response?.data?.detail || e.message}`))
        }
        break
      case 'manual_hedge':
        if (position) {
          if (!confirm(`确认手动对冲 ${symbol} #${position.id}？\n将卖出借来的现货(做空)+合约市价跟多。`)) break
          manualHedge(position.id)
            .then((r) => { alert(r.message || '对冲完成'); refreshPositions() })
            .catch((e) => alert(`对冲失败: ${e.response?.data?.detail || e.message}`))
        }
        break
      case 'manual_repay':
        if (position) {
          if (!confirm(`确认手动还币 ${symbol} #${position.id}？\n将买回的现币还清杠杆负债，持仓结算平仓。`)) break
          manualRepay(position.id)
            .then((r) => { alert(`${r.message}　盈亏: ${r.realized_pnl ?? '-'}`); refreshPositions() })
            .catch((e) => alert(`还币失败: ${e.response?.data?.detail || e.message}`))
        }
        break
      case 'partial_repay': {
        const subId = extra?.subAccountId as number | undefined
        if (!subId) break
        const amountStr = prompt(`部分还币 ${symbol}\n账户 #${subId}\n输入还币数量:`)
        if (!amountStr) break
        const amount = parseFloat(amountStr)
        if (isNaN(amount) || amount <= 0) {
          alert('请输入有效的正数')
          break
        }
        partialRepay(subId, symbol, amount)
          .then(() => { alert('还币成功'); refreshPositions() })
          .catch((e) => alert(`还币失败: ${e.response?.data?.detail || e.message}`))
        break
      }
      case 'clear_account': {
        const clearSubId = extra?.subAccountId as number | undefined
        if (!clearSubId) break
        const mode = confirm(
          `清除账户 #${clearSubId}\n\n确定 = 禁用并平仓\n取消 = 仅禁用`
        ) ? 'disable_and_close' as const : 'disable_only' as const
        if (!confirm(`确认${mode === 'disable_and_close' ? '禁用并平仓' : '仅禁用'}账户 #${clearSubId}？`)) break
        clearSubAccount(clearSubId, mode)
          .then(() => { alert('操作成功'); refreshPositions() })
          .catch((e: unknown) => {
            const resp = (e as { response?: { data?: { detail?: string } } })?.response
            alert(`操作失败: ${resp?.data?.detail || (e as Error)?.message || '未知错误'}`)
          })
        break
      }
      case 'view_detail':
        if (position) {
          alert(`持仓详情 ${symbol} #${position.id}\n状态: ${position.status}\n账户: ${position.account_note || '#' + position.sub_account_id}\n借币: ${position.borrow_qty}\n开仓利差: ${position.open_spread}%\n资金费: ${position.cumulative_funding_fee || '-'}\n利息: ${position.cumulative_interest || '-'}`)
        }
        break
      case 'cleanup_tail': {
        const maxStr = prompt('清理尾仓:平掉名义价值 ≤ N USDT 的碎仓\n输入阈值 (默认 10):', '10')
        if (maxStr === null) break
        const maxU = maxStr.trim() ? parseFloat(maxStr) : 10
        if (isNaN(maxU) || maxU <= 0) { alert('请输入有效阈值'); break }
        listTailPositions(maxU)
          .then((tails) => {
            if (!tails.length) { alert(`无 ≤ ${maxU}U 的尾仓`); return }
            const list = tails.map((t) => `${t.symbol} #${t.id}  ${parseFloat(t.open_usdt_amount).toFixed(1)}U`).join('\n')
            if (!confirm(`发现 ${tails.length} 个尾仓 (≤${maxU}U),将逐个市价平仓+买回+还币:\n\n${list}\n\n确认清理?`)) return
            cleanupTailPositions(maxU)
              .then((r: { message?: string; closed?: number; errors?: string[] }) => {
                alert(`${r.message || '清理完成'}${r.errors && r.errors.length ? '\n\n错误:\n' + r.errors.join('\n') : ''}`)
                refreshPositions()
              })
              .catch((e) => alert(`清理失败: ${e.response?.data?.detail || e.message}`))
          })
          .catch((e) => alert(`查询尾仓失败: ${e.response?.data?.detail || e.message}`))
        break
      }
      case 'refresh_borrowable': {
        const subId = (extra?.subAccountId as number | undefined) ?? position?.sub_account_id
        if (!subId) break
        getMaxBorrowable(subId, symbol)
          .then((d: { amount?: string | number }) => alert(`${symbol} @ 账户#${subId}\n最大可借: ${d.amount ?? d}`))
          .catch((e) => alert(`查询失败: ${e.response?.data?.detail || e.message}`))
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
        symbolRules={symbolRulesMap}
        delistingSymbols={delistingSymbols}
        riskySymbols={riskySymbols}
        throttleRate={throttleRate}
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
    </div>
  )
}
