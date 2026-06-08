import { useState, useEffect, useCallback } from 'react'
import { getSymbolRule, updateSymbolRule, resetSymbolRule } from '@/api/rules'
import { getSubAccounts } from '@/api/accounts'
import {
  getAccountSymbolRule,
  upsertAccountSymbolRule,
  resetAccountSymbolRule,
  batchUpdateAccountSymbolRules,
} from '@/api/accountSymbolRules'
import { listPresets, createPreset, type RulePreset } from '@/api/rulePresets'
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

const NUMERIC_FIELDS = [
  { key: 'remove_spread', label: '移除利差' },
  { key: 'open_spread', label: '开仓利差' },
  { key: 'order_amount', label: '下单金额' },
  { key: 'close_spread', label: '平仓利差' },
  { key: 'close_funding_ratio', label: '平仓资金费倍率' },
  { key: 'repay_spread', label: '还币利差' },
  { key: 'repay_funding_ratio', label: '还币资金费倍率' },
  { key: 'max_daily_interest_rate', label: '最大日利率' },
] as const

const ACCOUNT_FIELDS = [
  ...NUMERIC_FIELDS,
  { key: 'max_borrow_amount', label: '借币金额限制' },
] as const

export function SymbolRuleDialog({ symbol, initialAccountId, onClose }: SymbolRuleDialogProps) {
  const [activeTab, setActiveTab] = useState<'common' | number>(initialAccountId ?? 'common')
  const [symbolRule, setSymbolRule] = useState<Record<string, unknown>>({})
  const [accountRules, setAccountRules] = useState<Record<number, Record<string, unknown>>>({})
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchFields, setBatchFields] = useState<Record<string, string>>({})
  const [batchAccounts, setBatchAccounts] = useState<number[]>([])
  const [cellMenu, setCellMenu] = useState<{ x: number; y: number; fieldKey: string } | null>(null)
  const [presets, setPresets] = useState<RulePreset[]>([])
  const [presetName, setPresetName] = useState('')
  const [showSavePreset, setShowSavePreset] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true)
      try {
        const [rule, accts, presetList] = await Promise.all([
          getSymbolRule(symbol).catch(() => ({})),
          getSubAccounts(true),
          listPresets().catch(() => []),
        ])
        setPresets(presetList)
        setSymbolRule(rule)
        setAccounts(accts)

        const arMap: Record<number, Record<string, unknown>> = {}
        await Promise.all(
          accts.map(async (a: SubAccount) => {
            try {
              const ar = await getAccountSymbolRule(a.id, symbol)
              arMap[a.id] = ar as unknown as Record<string, unknown>
            } catch {
              arMap[a.id] = {}
            }
          }),
        )
        setAccountRules(arMap)
      } catch {
        // ignore
      }
      setLoading(false)
    }
    loadAll()
  }, [symbol])

  useEffect(() => {
    if (initialAccountId) setActiveTab(initialAccountId)
  }, [initialAccountId])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      if (activeTab === 'common') {
        await updateSymbolRule(symbol, { ...symbolRule, is_temporary: true })
      } else {
        const data = accountRules[activeTab] || {}
        await upsertAccountSymbolRule(activeTab, symbol, data)
      }
      addToast('规则已保存', 'success')
      onClose()
    } catch {
      addToast('保存失败', 'error')
    }
    setSaving(false)
  }, [symbol, activeTab, symbolRule, accountRules, onClose, addToast])

  const handleReset = useCallback(async () => {
    if (!confirm(activeTab === 'common' ? '确认恢复通用规则？' : '确认重置该账户的自定义规则？')) return
    try {
      if (activeTab === 'common') {
        await resetSymbolRule(symbol)
      } else {
        await resetAccountSymbolRule(activeTab, symbol)
      }
      addToast('已重置', 'success')
      onClose()
    } catch {
      addToast('重置失败', 'error')
    }
  }, [symbol, activeTab, onClose, addToast])

  const handleBatchSave = useCallback(async () => {
    if (batchAccounts.length === 0) {
      addToast('请选择至少一个账户', 'error')
      return
    }
    const validFields = Object.fromEntries(
      Object.entries(batchFields).filter(([, v]) => v !== ''),
    )
    if (Object.keys(validFields).length === 0) {
      addToast('请填写至少一个字段', 'error')
      return
    }
    try {
      await batchUpdateAccountSymbolRules(
        batchAccounts.map((id) => ({
          sub_account_id: id,
          symbol,
          data: validFields,
        })),
      )
      addToast('批量修改成功', 'success')
      setBatchOpen(false)
      onClose()
    } catch {
      addToast('批量修改失败', 'error')
    }
  }, [batchAccounts, batchFields, symbol, onClose, addToast])

  const handleRestoreField = useCallback(async (fieldKey: string) => {
    if (activeTab === 'common') return
    try {
      await upsertAccountSymbolRule(activeTab, symbol, { [fieldKey]: null })
      setAccountRules(prev => ({
        ...prev,
        [activeTab]: { ...prev[activeTab], [fieldKey]: null },
      }))
      addToast(`已恢复 "${fieldKey}" 到通用规则`, 'success')
    } catch {
      addToast('恢复失败', 'error')
    }
    setCellMenu(null)
  }, [activeTab, symbol, addToast])

  const handleCellContextMenu = useCallback((e: React.MouseEvent, fieldKey: string, modified: boolean) => {
    if (activeTab === 'common' || !modified) return
    e.preventDefault()
    setCellMenu({ x: e.clientX, y: e.clientY, fieldKey })
  }, [activeTab])

  useEffect(() => {
    const close = () => setCellMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const currentRule = activeTab === 'common' ? symbolRule : (accountRules[activeTab] || {})
  const setCurrentRule = (v: Record<string, unknown>) => {
    if (activeTab === 'common') {
      setSymbolRule(v)
    } else {
      setAccountRules({ ...accountRules, [activeTab]: v })
    }
  }

  const isModified = (key: string, value: unknown) => {
    if (activeTab === 'common') return false
    return value != null && value !== '' && value !== symbolRule[key]
  }

  const source = symbolRule.is_temporary ? '自定义临时规则' : '通用规则'
  const fields = activeTab === 'common' ? NUMERIC_FIELDS : ACCOUNT_FIELDS

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="w-[calc(100vw-2rem)] max-w-[480px] max-h-[85vh] overflow-y-auto rounded border border-border bg-[#141420] p-4 space-y-3 shadow-2xl"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">单一规则 — {symbol}</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-sm">✕</button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-border pb-1 overflow-x-auto">
          <button
            onClick={() => setActiveTab('common')}
            className={`px-2 py-0.5 text-[11px] rounded-t whitespace-nowrap ${activeTab === 'common' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
          >
            通用
          </button>
          {accounts.map((a) => (
            <button
              key={a.id}
              onClick={() => setActiveTab(a.id)}
              className={`px-2 py-0.5 text-[11px] rounded-t whitespace-nowrap ${activeTab === a.id ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
            >
              {a.note}
            </button>
          ))}
        </div>

        {activeTab === 'common' && (
          <div className="flex items-center gap-4 text-[11px] text-muted-foreground flex-wrap">
            <span>来源: <span className="text-primary">{source}</span></span>
            {presets.length > 0 && (
              <select
                className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
                defaultValue=""
                onChange={(e) => {
                  const p = presets.find(x => x.id === Number(e.target.value))
                  if (!p) return
                  const filled: Record<string, unknown> = { ...symbolRule }
                  for (const { key } of NUMERIC_FIELDS) {
                    if (p[key as keyof RulePreset] != null) filled[key] = p[key as keyof RulePreset]
                  }
                  setSymbolRule(filled)
                  addToast(`已填充预设 "${p.name}"`, 'info')
                  e.target.value = ''
                }}
              >
                <option value="">选择预设...</option>
                {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <button
              onClick={() => setShowSavePreset(!showSavePreset)}
              className="px-1.5 py-0.5 text-[10px] border border-border rounded hover:bg-accent/50"
            >
              保存为预设
            </button>
            {showSavePreset && (
              <span className="inline-flex items-center gap-1">
                <input
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value)}
                  placeholder="预设名称"
                  className="w-20 bg-[#1a1a22] border border-border rounded px-1 py-0.5 text-[10px] text-foreground focus:outline-none focus:border-primary"
                />
                <button
                  onClick={async () => {
                    if (!presetName.trim()) { addToast('请输入预设名称', 'error'); return }
                    try {
                      const payload: Record<string, unknown> = { name: presetName.trim() }
                      for (const { key } of NUMERIC_FIELDS) {
                        if (symbolRule[key] != null && symbolRule[key] !== '') payload[key] = Number(symbolRule[key])
                      }
                      const created = await createPreset(payload)
                      setPresets(prev => [...prev, created])
                      setShowSavePreset(false)
                      setPresetName('')
                      addToast(`预设 "${created.name}" 已保存`, 'success')
                    } catch { addToast('保存预设失败', 'error') }
                  }}
                  className="px-1.5 py-0.5 text-[10px] bg-primary/20 text-primary rounded"
                >
                  确认
                </button>
              </span>
            )}
          </div>
        )}

        {loading ? (
          <p className="py-4 text-center text-muted-foreground text-xs">加载中...</p>
        ) : (
          <div className="space-y-2">
            {fields.map(({ key, label }) => {
              const val = currentRule[key]
              const modified = isModified(key, val)
              const displayVal = key === 'max_borrow_amount' && val !== null && val !== '' && Number(val) === 0
                ? '不借'
                : ''
              return (
                <div key={key} className="flex items-center gap-2">
                  <label className="text-[11px] text-muted-foreground w-28 shrink-0 text-right">{label}</label>
                  <input
                    value={displayVal || String(val ?? '')}
                    onChange={(e) => setCurrentRule({ ...currentRule, [key]: e.target.value })}
                    onContextMenu={(e) => handleCellContextMenu(e, key, modified)}
                    placeholder={activeTab !== 'common' ? String(symbolRule[key] ?? '') : undefined}
                    className={`flex-1 bg-[#1a1a22] border border-border rounded px-2 py-1 text-xs focus:outline-none focus:border-primary ${modified ? 'text-amber-400 border-amber-400/30' : 'text-foreground'}`}
                  />
                  {key === 'remove_spread' && Number(val) <= 0.5 && val != null && val !== '' && (
                    <span className="text-[10px] text-amber-500">⚠</span>
                  )}
                </div>
              )
            })}

            {activeTab === 'common' && (
              <>
                <div className="flex items-center gap-2">
                  <label className="text-[11px] text-muted-foreground w-28 shrink-0 text-right">禁止移除</label>
                  <button
                    onClick={() => setCurrentRule({ ...currentRule, allow_remove: !!currentRule.allow_remove ? false : true })}
                    className={`px-2 py-0.5 rounded text-[11px] ${currentRule.allow_remove === false ? 'bg-negative/20 text-negative' : 'bg-positive/20 text-positive'}`}
                  >
                    {currentRule.allow_remove === false ? '已禁止' : '允许'}
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-[11px] text-muted-foreground w-28 shrink-0 text-right">禁止还币</label>
                  <button
                    onClick={() => setCurrentRule({ ...currentRule, allow_repay: !!currentRule.allow_repay ? false : true })}
                    className={`px-2 py-0.5 rounded text-[11px] ${currentRule.allow_repay === false ? 'bg-negative/20 text-negative' : 'bg-positive/20 text-positive'}`}
                  >
                    {currentRule.allow_repay === false ? '已禁止' : '允许'}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="flex items-center justify-between pt-2 border-t border-border">
          <button
            onClick={handleReset}
            className="px-3 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded hover:bg-accent"
          >
            恢复通用
          </button>
          <div className="flex gap-2">
            <button
              onClick={() => setBatchOpen(true)}
              className="px-3 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded hover:bg-accent"
            >
              批量修改
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-3 py-1 text-xs bg-primary/20 text-primary rounded hover:bg-primary/30 disabled:opacity-40"
            >
              保存
            </button>
          </div>
        </div>

        {/* Per-cell restore context menu (B1) */}
        {cellMenu && (
          <div
            className="fixed z-[60] min-w-[140px] rounded border border-border bg-[#141420] py-1 shadow-xl"
            style={{ left: cellMenu.x, top: cellMenu.y }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="flex w-full items-center px-3 py-1.5 text-[11px] hover:bg-accent/50 transition-colors text-left text-amber-400"
              onClick={() => handleRestoreField(cellMenu.fieldKey)}
            >
              恢复此项到通用规则
            </button>
          </div>
        )}

        {/* Batch dialog overlay */}
        {batchOpen && (
          <div className="absolute inset-0 bg-black/30 flex items-center justify-center z-10" onClick={() => setBatchOpen(false)}>
            <div className="w-[calc(100vw-3rem)] max-w-80 bg-[#141420] border border-border rounded p-3 space-y-2" onClick={(e) => e.stopPropagation()}>
              <h4 className="text-xs font-semibold">批量修改 — {symbol}</h4>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">选择账户:</p>
                <div className="flex flex-wrap gap-1">
                  {accounts.map((a) => (
                    <button
                      key={a.id}
                      onClick={() =>
                        setBatchAccounts((prev) =>
                          prev.includes(a.id) ? prev.filter((x) => x !== a.id) : [...prev, a.id],
                        )
                      }
                      className={`px-2 py-0.5 text-[10px] rounded ${batchAccounts.includes(a.id) ? 'bg-primary/30 text-primary' : 'bg-accent text-muted-foreground'}`}
                    >
                      {a.note}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">设置值 (留空跳过):</p>
                {ACCOUNT_FIELDS.map(({ key, label }) => (
                  <div key={key} className="flex items-center gap-1">
                    <label className="text-[10px] w-24 text-right text-muted-foreground">{label}</label>
                    <input
                      value={batchFields[key] || ''}
                      onChange={(e) => setBatchFields({ ...batchFields, [key]: e.target.value })}
                      className="flex-1 bg-[#1a1a22] border border-border rounded px-1 py-0.5 text-[10px]"
                    />
                  </div>
                ))}
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
