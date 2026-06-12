import { useState, useEffect, useCallback } from 'react'
import { getSymbolRule, updateSymbolRule, resetSymbolRule } from '@/api/rules'
import { getSubAccounts } from '@/api/accounts'
import {
  getAccountSymbolRule,
  upsertAccountSymbolRule,
  resetAccountSymbolRule,
  batchUpdateAccountSymbolRules,
} from '@/api/accountSymbolRules'
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

// 综合优化后的列(coin 现有字段 + coinmini 图样式 + 新增「金额限制」)
const COLS = [
  { key: 'open_spread', label: '开点差' },
  { key: 'close_spread', label: '平点差' },
  { key: 'remove_spread', label: '移除差' },
  { key: 'order_amount', label: '单笔挂单' },
  { key: 'max_borrow_amount', label: '金额限制' },   // 借币金额上限(USDT,=maxBorrowable 封顶)
  { key: 'close_funding_ratio', label: '平资息' },
  { key: 'repay_spread', label: '还币开' },
  { key: 'repay_funding_ratio', label: '还资息' },
  { key: 'max_daily_interest_rate', label: '日利率' },
] as const

type Row = Record<string, unknown>

export function SymbolRuleDialog({ symbol, onClose }: SymbolRuleDialogProps) {
  const [symbolRule, setSymbolRule] = useState<Row>({})        // 通用(SymbolRule)
  const [accountRules, setAccountRules] = useState<Record<number, Row>>({}) // 各账户(AccountSymbolRule)
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState<Set<string>>(new Set())   // 'common' | account id
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchFields, setBatchFields] = useState<Record<string, string>>({})
  const [batchAccounts, setBatchAccounts] = useState<number[]>([])
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true)
      try {
        const [rule, accts] = await Promise.all([
          getSymbolRule(symbol).catch(() => ({})),
          getSubAccounts(true),
        ])
        setSymbolRule(rule as Row)
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

  const setCommon = (key: string, v: string) => { setSymbolRule((p) => ({ ...p, [key]: v })); markDirty('common') }
  const setAcct = (id: number, key: string, v: string) => {
    setAccountRules((p) => ({ ...p, [id]: { ...(p[id] || {}), [key]: v } })); markDirty(String(id))
  }

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const tasks: Promise<unknown>[] = []
      if (dirty.has('common')) tasks.push(updateSymbolRule(symbol, { ...symbolRule, is_temporary: true }))
      for (const a of accounts) {
        if (dirty.has(String(a.id))) tasks.push(upsertAccountSymbolRule(a.id, symbol, accountRules[a.id] || {}))
      }
      if (tasks.length === 0) { addToast('无改动', 'info'); setSaving(false); return }
      await Promise.all(tasks)
      addToast(`已保存 ${tasks.length} 项`, 'success')
      onClose()
    } catch { addToast('保存失败', 'error') }
    setSaving(false)
  }, [symbol, symbolRule, accountRules, accounts, dirty, onClose, addToast])

  const handleResetCommon = useCallback(async () => {
    if (!confirm('确认恢复该币种「通用」规则为默认?')) return
    try { await resetSymbolRule(symbol); addToast('通用已重置', 'success'); onClose() }
    catch { addToast('重置失败', 'error') }
  }, [symbol, onClose, addToast])

  const handleResetAcct = useCallback(async (id: number) => {
    try {
      await resetAccountSymbolRule(id, symbol)
      setAccountRules((p) => ({ ...p, [id]: {} }))
      addToast('该账户已恢复跟随通用', 'success')
    } catch { addToast('恢复失败', 'error') }
  }, [symbol, addToast])

  const handleBatchSave = useCallback(async () => {
    if (batchAccounts.length === 0) { addToast('请选择至少一个账户', 'error'); return }
    const valid = Object.fromEntries(Object.entries(batchFields).filter(([, v]) => v !== ''))
    if (Object.keys(valid).length === 0) { addToast('请填写至少一个字段', 'error'); return }
    try {
      await batchUpdateAccountSymbolRules(batchAccounts.map((id) => ({ sub_account_id: id, symbol, data: valid })))
      addToast('批量修改成功', 'success'); setBatchOpen(false); onClose()
    } catch { addToast('批量修改失败', 'error') }
  }, [batchAccounts, batchFields, symbol, onClose, addToast])

  const cellCls = 'w-14 bg-[#1a1a22] border border-border rounded px-1 py-0.5 text-[10px] text-foreground focus:outline-none focus:border-primary text-right'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[calc(100vw-1.5rem)] max-w-[900px] max-h-[88vh] overflow-auto rounded border border-border bg-[#141420] p-3 space-y-2 shadow-2xl">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">单一规则 — 币种: <span className="text-primary">{symbol.replace('USDT', '')}</span> <span className="text-[10px] text-muted-foreground">来源: 单一规则</span></h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-sm">✕</button>
        </div>

        {loading ? (
          <p className="py-6 text-center text-muted-foreground text-xs">加载中...</p>
        ) : (
          <div className="overflow-x-auto rounded border border-border">
            <table className="w-full min-w-[820px] text-[10px]">
              <thead>
                <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                  <th className="px-1.5 py-1.5 text-left font-medium">备注</th>
                  {COLS.map((c) => <th key={c.key} className="px-1 py-1.5 text-right font-medium">{c.label}</th>)}
                  <th className="px-1 py-1.5 text-center font-medium">移除/还币</th>
                  <th className="px-1 py-1.5 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {/* 通用 行 */}
                <tr className="border-b border-border/40 bg-primary/5">
                  <td className="px-1.5 py-1 font-medium text-primary">通用</td>
                  {COLS.map((c) => (
                    <td key={c.key} className="px-1 py-1 text-right">
                      <input className={cellCls} value={String(symbolRule[c.key] ?? '')}
                        onChange={(e) => setCommon(c.key, e.target.value)} />
                    </td>
                  ))}
                  <td className="px-1 py-1 text-center whitespace-nowrap">
                    <button onClick={() => { setSymbolRule((p) => ({ ...p, allow_remove: p.allow_remove === false ? true : false })); markDirty('common') }}
                      className={`px-1 py-0.5 rounded text-[9px] mr-0.5 ${symbolRule.allow_remove === false ? 'bg-negative/20 text-negative' : 'bg-positive/20 text-positive'}`}>
                      {symbolRule.allow_remove === false ? '禁移' : '允移'}
                    </button>
                    <button onClick={() => { setSymbolRule((p) => ({ ...p, allow_repay: p.allow_repay === false ? true : false })); markDirty('common') }}
                      className={`px-1 py-0.5 rounded text-[9px] ${symbolRule.allow_repay === false ? 'bg-negative/20 text-negative' : 'bg-positive/20 text-positive'}`}>
                      {symbolRule.allow_repay === false ? '禁还' : '允还'}
                    </button>
                  </td>
                  <td className="px-1 py-1 text-center">
                    <button onClick={handleResetCommon} className="px-1.5 py-0.5 text-[9px] border border-border rounded hover:bg-accent">恢复默认</button>
                  </td>
                </tr>
                {/* 各账户 行(留空=跟随通用,placeholder 显示通用值) */}
                {accounts.map((a) => {
                  const ar = accountRules[a.id] || {}
                  return (
                    <tr key={a.id} className="border-b border-border/20 hover:bg-accent/10">
                      <td className="px-1.5 py-1 font-medium whitespace-nowrap">{a.note}</td>
                      {COLS.map((c) => {
                        const v = ar[c.key]
                        const modified = v != null && v !== '' && String(v) !== String(symbolRule[c.key] ?? '')
                        return (
                          <td key={c.key} className="px-1 py-1 text-right">
                            <input className={`${cellCls} ${modified ? 'text-amber-400 border-amber-400/30' : ''}`}
                              value={String(v ?? '')} placeholder={String(symbolRule[c.key] ?? '')}
                              onChange={(e) => setAcct(a.id, c.key, e.target.value)} />
                          </td>
                        )
                      })}
                      <td className="px-1 py-1 text-center text-muted-foreground/40">—</td>
                      <td className="px-1 py-1 text-center">
                        <button onClick={() => handleResetAcct(a.id)} className="px-1.5 py-0.5 text-[9px] border border-border rounded hover:bg-accent">恢复通用</button>
                      </td>
                    </tr>
                  )
                })}
                {accounts.length === 0 && <tr><td colSpan={COLS.length + 3} className="py-4 text-center text-muted-foreground">无子账户</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between pt-1">
          <span className="text-[10px] text-muted-foreground">账户行留空 = 跟随「通用」;金额限制 = 借币上限(USDT,maxBorrowable 封顶)</span>
          <div className="flex gap-2">
            <button onClick={() => setBatchOpen(true)} className="px-3 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded hover:bg-accent">批量修改</button>
            <button onClick={handleSave} disabled={saving} className="px-3 py-1 text-xs bg-primary/20 text-primary rounded hover:bg-primary/30 disabled:opacity-40">保存</button>
          </div>
        </div>

        {batchOpen && (
          <div className="absolute inset-0 bg-black/40 flex items-center justify-center z-10" onClick={() => setBatchOpen(false)}>
            <div className="w-[calc(100vw-3rem)] max-w-96 bg-[#141420] border border-border rounded p-3 space-y-2" onClick={(e) => e.stopPropagation()}>
              <h4 className="text-xs font-semibold">批量修改 — {symbol.replace('USDT', '')}</h4>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">选择账户:</p>
                <div className="flex flex-wrap gap-1">
                  {accounts.map((a) => (
                    <button key={a.id}
                      onClick={() => setBatchAccounts((p) => p.includes(a.id) ? p.filter((x) => x !== a.id) : [...p, a.id])}
                      className={`px-2 py-0.5 text-[10px] rounded ${batchAccounts.includes(a.id) ? 'bg-primary/30 text-primary' : 'bg-accent text-muted-foreground'}`}>
                      {a.note}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">设置值 (留空跳过):</p>
                <div className="grid grid-cols-2 gap-1">
                  {COLS.map((c) => (
                    <div key={c.key} className="flex items-center gap-1">
                      <label className="text-[10px] w-14 text-right text-muted-foreground">{c.label}</label>
                      <input value={batchFields[c.key] || ''} onChange={(e) => setBatchFields({ ...batchFields, [c.key]: e.target.value })}
                        className="flex-1 bg-[#1a1a22] border border-border rounded px-1 py-0.5 text-[10px]" />
                    </div>
                  ))}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button onClick={() => setBatchOpen(false)} className="px-2 py-0.5 text-[10px] border border-border rounded">取消</button>
                <button onClick={handleBatchSave} className="px-2 py-0.5 text-[10px] bg-primary/20 text-primary rounded">确认批量</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
