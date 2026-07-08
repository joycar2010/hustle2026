import { useState, useEffect, useCallback } from 'react'
import { getSymbolRule, updateSymbolRule, resetSymbolRule, getGlobalRules } from '@/api/rules'
import { getSubAccounts } from '@/api/accounts'
import { getAccountSymbolRule, upsertAccountSymbolRule } from '@/api/accountSymbolRules'
import { partialRepay } from '@/api/engine'
import { useBalanceStore } from '@/stores/balanceStore'
import { confirmDialog } from '@/components/ui/confirm'
import { useToastStore } from '@/components/ui/toast'

interface SymbolRuleDialogProps {
  symbol: string
  initialAccountId?: number
  onClose: () => void
}

interface SubAccount {
  id: number
  note: string
  is_enabled: boolean
}

// 列定义:type=select(跟单 market/limit)默认数值;w=按数据实际大小给宽,避免横向滚动
// 注:日利率(max_daily_interest_rate,引擎零消费=孤儿)与备注(per-symbol 标签)已摘除
const COLS = [
  { key: 'borrow_spread', label: '挂单差', w: 'w-12' },
  { key: 'open_spread', label: '开点差', w: 'w-12' },
  { key: 'close_spread', label: '平点差', w: 'w-12' },
  { key: 'remove_spread', label: '移除差', w: 'w-12' },
  { key: 'order_amount', label: '单笔挂单', w: 'w-16' },
  { key: 'max_borrow_amount', label: '金额限制', w: 'w-16' },
  { key: 'close_funding_ratio', label: '平资息', w: 'w-12' },
  { key: 'repay_spread', label: '还币开', w: 'w-12' },
  { key: 'repay_funding_ratio', label: '还资息', w: 'w-12' },
] as const

type Row = Record<string, unknown>

const CELL_BASE = 'bg-[#1a1a22] border border-border rounded px-1 py-0.5 text-[10px] text-foreground focus:outline-none focus:border-primary'

export function SymbolRuleDialog({ symbol, onClose }: SymbolRuleDialogProps) {
  const [symbolRule, setSymbolRule] = useState<Row>({})        // 批量/基线(SymbolRule)
  const [globalRules, setGlobalRules] = useState<Row>({})      // 全局规则(批量行 placeholder 默认值源)
  const [accountRules, setAccountRules] = useState<Record<number, Row>>({}) // 各账户(AccountSymbolRule)
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState<Set<string>>(new Set())   // 'common' | account id
  const [repaying, setRepaying] = useState<number | null>(null)
  const addToast = useToastStore((s) => s.addToast)
  const balances = useBalanceStore((s) => s.balances)
  const markRepaid = useBalanceStore((s) => s.markRepaid)

  // 某账户对当前币的持币(已借本金+利息),数据来自 balance 实时快照 symbol_margin
  const heldOf = useCallback((accountId: number) => {
    const bal = balances.find((b) => b.account_id === accountId)
    const sm = bal?.symbol_margin?.[symbol]
    const borrowed = sm?.borrowed ?? 0
    const interest = sm?.interest ?? 0
    return { borrowed, interest, total: borrowed + interest }
  }, [balances, symbol])

  const handleRepayOne = useCallback(async (accountId: number, note: string) => {
    const { borrowed, interest, total } = heldOf(accountId)
    if (total <= 0) { addToast('该账户当前无持币', 'info'); return }
    const base = symbol.replace('USDT', '')
    if (!(await confirmDialog({
      title: '还币',
      message: `确认为 ${note} 还清 ${base}？\n本金 ${borrowed.toFixed(6)} + 利息 ${interest.toFixed(6)} ≈ ${total.toFixed(6)} ${base}`,
      danger: true,
    }))) return
    setRepaying(accountId)
    try {
      await partialRepay(accountId, symbol, total)
      markRepaid(accountId, symbol)   // 乐观清零 → 持币列即时归"—",下次WS推送对账
      addToast(`${note} 还币已提交`, 'success')
    } catch (e) {
      addToast(`还币失败: ${(e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error)?.message}`, 'error')
    }
    setRepaying(null)
  }, [heldOf, symbol, addToast, markRepaid])

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true)
      try {
        const [rule, accts, grules] = await Promise.all([
          getSymbolRule(symbol).catch(() => ({})),
          getSubAccounts(true),
          getGlobalRules().catch(() => ({})),
        ])
        setSymbolRule(rule as Row)
        setGlobalRules(grules as Row)
        setAccounts(accts)
        const arMap: Record<number, Row> = {}
        await Promise.all(accts.map(async (a: SubAccount) => {
          try { arMap[a.id] = (await getAccountSymbolRule(a.id, symbol)) as unknown as Row } catch { arMap[a.id] = {} }
        }))
        setAccountRules(arMap)
      } catch { /* ignore */ }
      setLoading(false)
    }
    loadAll()
  }, [symbol])

  const markDirty = (k: string) => setDirty((p) => new Set(p).add(k))

  const setAcct = (id: number, key: string, v: string) => {
    setAccountRules((p) => ({ ...p, [id]: { ...(p[id] || {}), [key]: v } })); markDirty(String(id))
  }

  // 批量行某列编辑 = 设基线 + 清掉该列所有账户的覆盖 → 整列(含原本改过的)跟随新值
  const setBatch = (key: string, v: string) => {
    const affected = accounts
      .filter((a) => { const cur = accountRules[a.id]?.[key]; return cur !== undefined && cur !== '' })
      .map((a) => a.id)
    setSymbolRule((p) => ({ ...p, [key]: v }))
    setAccountRules((prev) => {
      const next = { ...prev }
      for (const id of affected) next[id] = { ...(next[id] || {}), [key]: '' }
      return next
    })
    setDirty((prev) => {
      const n = new Set(prev); n.add('common'); affected.forEach((id) => n.add(String(id))); return n
    })
  }

  const toggleCommonBool = (key: 'allow_remove' | 'allow_repay') => {
    setSymbolRule((p) => ({ ...p, [key]: p[key] === false ? true : false })); markDirty('common')
  }

  // 单格右键恢复:清该账户该字段覆盖 → 回到跟随批量(保存后生效)
  const restoreCell = (id: number, key: string) => (e: React.MouseEvent) => {
    e.preventDefault()
    setAcct(id, key, '')
  }

  // 整行恢复:清该账户全部覆盖字段 → 整行跟随批量
  const restoreRow = (id: number) => {
    setAccountRules((p) => ({ ...p, [id]: Object.fromEntries(COLS.map((c) => [c.key, ''])) }))
    markDirty(String(id))
  }

  // 保存前清洗:空串→null(才能真正清覆盖;否则 Decimal('') 会 422),只发列字段
  const sanitize = (row: Row): Record<string, unknown> => {
    const out: Record<string, unknown> = {}
    for (const c of COLS) {
      if (!(c.key in row)) continue
      const val = row[c.key]
      out[c.key] = (val === '' || val === undefined) ? null : val
    }
    return out
  }

  const handleSave = useCallback(async () => {
    // 平点差负值防误设:平仓条件是「点差 < 平点差」,负值=点差要跌破该负值才平,
    // 正常行情下几乎永不触发(把 -1 当"立即平仓"是高频误用;立即平仓走右键→强制平仓)
    const isNeg = (v: unknown) => v !== '' && v !== undefined && v !== null && Number(v) < 0
    const negRows: string[] = []
    if (dirty.has('common') && isNeg(symbolRule.close_spread)) negRows.push('批量')
    for (const a of accounts) {
      if (dirty.has(String(a.id)) && isNeg(accountRules[a.id]?.close_spread)) negRows.push(a.note)
    }
    if (negRows.length > 0 && !(await confirmDialog({
      title: '平点差为负值 — 几乎永不触发',
      message: `【${negRows.join('、')}】的平点差是负数。\n平仓条件为「点差 < 平点差」:负值意味着点差要跌破该负值才会平仓,正常行情下永远等不到。\n若想立即平仓:持仓行右键 →「强制平仓」。\n\n仍要按负值保存吗?`,
      danger: true,
    }))) return
    setSaving(true)
    try {
      const tasks: Promise<unknown>[] = []
      if (dirty.has('common')) {
        const payload: Record<string, unknown> = { ...sanitize(symbolRule), is_temporary: true }
        if (symbolRule.allow_remove !== undefined) payload.allow_remove = symbolRule.allow_remove
        if (symbolRule.allow_repay !== undefined) payload.allow_repay = symbolRule.allow_repay
        tasks.push(updateSymbolRule(symbol, payload))
      }
      for (const a of accounts) {
        if (dirty.has(String(a.id))) tasks.push(upsertAccountSymbolRule(a.id, symbol, sanitize(accountRules[a.id] || {})))
      }
      if (tasks.length === 0) { addToast('无改动', 'info'); setSaving(false); return }
      await Promise.all(tasks)
      addToast(`已保存 ${tasks.length} 项`, 'success')
      onClose()
    } catch { addToast('保存失败(请检查数值是否合法)', 'error') }
    setSaving(false)
  }, [symbol, symbolRule, accountRules, accounts, dirty, onClose, addToast])

  const handleResetCommon = useCallback(async () => {
    if (!confirm('确认恢复该币种「批量/基线」规则为系统默认?')) return
    try { await resetSymbolRule(symbol); addToast('已重置为默认', 'success'); onClose() }
    catch { addToast('重置失败', 'error') }
  }, [symbol, onClose, addToast])

  // 渲染一个可编辑单元格(批量行 or 账户行)
  const renderCell = (
    col: typeof COLS[number],
    value: unknown,
    placeholder: string,
    modified: boolean,
    onChange: (v: string) => void,
    onCtx?: (e: React.MouseEvent) => void,
  ) => {
    const cls = `${col.w} ${CELL_BASE} text-right ${modified ? 'text-amber-400 border-amber-400/50 bg-amber-400/10' : ''}`
    if ('type' in col && col.type === 'select') {
      return (
        <select className={cls} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} onContextMenu={onCtx}>
          <option value="">{placeholder ? `跟随(${placeholder})` : '跟随'}</option>
          <option value="market">market</option>
          <option value="limit">limit</option>
        </select>
      )
    }
    return (
      <input className={cls} value={String(value ?? '')} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)} onContextMenu={onCtx} />
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-2">
      <div className="w-fit max-w-[calc(100vw-1rem)] max-h-[92vh] overflow-auto rounded border border-border bg-[#141420] p-3 space-y-2 shadow-2xl">
        <div className="flex items-center justify-between gap-4">
          <h3 className="text-sm font-semibold whitespace-nowrap">单一规则 — 币种: <span className="text-primary">{symbol.replace('USDT', '')}</span></h3>
          <span className="text-[10px] text-muted-foreground flex-1">顶行「批量」改某列 → 整列所有账户跟随;账户格<span className="text-amber-400">变色=单一规则</span>,<span className="text-foreground">右键单格</span>或行尾「恢复整行」可回到批量;留空=跟随批量</span>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-sm">✕</button>
        </div>

        {loading ? (
          <p className="py-6 text-center text-muted-foreground text-xs">加载中...</p>
        ) : (
          <table className="text-[10px] border-collapse">
            <thead>
              <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                <th className="px-1.5 py-1.5 text-left font-medium">备注</th>
                <th className="px-1 py-1.5 text-center font-medium whitespace-nowrap">持币</th>
                {COLS.map((c) => <th key={c.key} className="px-1 py-1.5 text-center font-medium whitespace-nowrap">{c.label}</th>)}
                <th className="px-1 py-1.5 text-center font-medium whitespace-nowrap">移除/还币</th>
                <th className="px-1 py-1.5 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {/* 批量 行(基线 + 批量改列) */}
              <tr className="border-b border-border/40 bg-primary/5">
                <td className="px-1.5 py-1 font-medium text-primary whitespace-nowrap">批量</td>
                <td className="px-1 py-1 text-center text-muted-foreground/40">—</td>
                {COLS.map((c) => (
                  <td key={c.key} className="px-1 py-1 text-center">
                    {/* 批量行留空=跟随全局;placeholder 显示全局值,让用户点进来就看到全局默认,改了才落自定义 */}
                    {renderCell(c, symbolRule[c.key], String(globalRules[c.key] ?? ''), false, (v) => setBatch(c.key, v))}
                  </td>
                ))}
                <td className="px-1 py-1 text-center whitespace-nowrap">
                  <button onClick={() => toggleCommonBool('allow_remove')}
                    className={`px-1 py-0.5 rounded text-[9px] mr-0.5 ${symbolRule.allow_remove === false ? 'bg-negative/20 text-negative' : 'bg-positive/20 text-positive'}`}>
                    {symbolRule.allow_remove === false ? '禁移' : '允移'}
                  </button>
                  <button onClick={() => toggleCommonBool('allow_repay')}
                    className={`px-1 py-0.5 rounded text-[9px] ${symbolRule.allow_repay === false ? 'bg-negative/20 text-negative' : 'bg-positive/20 text-positive'}`}>
                    {symbolRule.allow_repay === false ? '禁还' : '允还'}
                  </button>
                </td>
                <td className="px-1 py-1 text-center">
                  <button onClick={handleResetCommon} className="px-1.5 py-0.5 text-[9px] border border-border rounded hover:bg-accent whitespace-nowrap">恢复默认</button>
                </td>
              </tr>
              {/* 各账户 行(留空=跟随批量,placeholder 显示批量值;右键单格恢复) */}
              {accounts.map((a) => {
                const ar = accountRules[a.id] || {}
                return (
                  <tr key={a.id} className="border-b border-border/20 hover:bg-accent/10">
                    <td className="px-1.5 py-1 font-medium whitespace-nowrap">{a.note}</td>
                    <td className="px-1 py-1 text-center whitespace-nowrap">
                      {(() => {
                        const held = heldOf(a.id)
                        if (held.total <= 0) return <span className="text-muted-foreground/40">—</span>
                        return (
                          <span className="inline-flex items-center gap-1">
                            <span className="text-amber-400 font-mono" title={`本金${held.borrowed.toFixed(6)} 利息${held.interest.toFixed(6)}`}>{held.borrowed.toFixed(4)}</span>
                            <button
                              onClick={() => handleRepayOne(a.id, a.note)}
                              disabled={repaying === a.id}
                              className="px-1 py-0.5 rounded text-[9px] bg-negative/20 text-negative hover:bg-negative/30 disabled:opacity-40"
                            >{repaying === a.id ? '还币中' : '还币'}</button>
                          </span>
                        )
                      })()}
                    </td>
                    {COLS.map((c) => {
                      const v = ar[c.key]
                      const baseline = String(symbolRule[c.key] ?? globalRules[c.key] ?? '')
                      const modified = v != null && v !== '' && String(v) !== baseline
                      return (
                        <td key={c.key} className="px-1 py-1 text-center" title={modified ? '右键恢复为批量值' : undefined}>
                          {renderCell(c, v, baseline, modified, (val) => setAcct(a.id, c.key, val), restoreCell(a.id, c.key))}
                        </td>
                      )
                    })}
                    <td className="px-1 py-1 text-center text-muted-foreground/40">—</td>
                    <td className="px-1 py-1 text-center">
                      <button onClick={() => restoreRow(a.id)} className="px-1.5 py-0.5 text-[9px] border border-border rounded hover:bg-accent whitespace-nowrap">恢复整行</button>
                    </td>
                  </tr>
                )
              })}
              {accounts.length === 0 && <tr><td colSpan={COLS.length + 4} className="py-4 text-center text-muted-foreground">无子账户</td></tr>}
            </tbody>
          </table>
        )}

        <div className="flex items-center justify-end pt-1">
          <button onClick={handleSave} disabled={saving} className="px-4 py-1 text-xs bg-primary/20 text-primary rounded hover:bg-primary/30 disabled:opacity-40">保存</button>
        </div>
      </div>
    </div>
  )
}
