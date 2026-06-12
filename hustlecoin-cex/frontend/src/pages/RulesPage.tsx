import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getGlobalRules, updateGlobalRules, getFundRules, updateFundRules } from '@/api/rules'
import { getFeishuConfig, updateFeishuConfig, testFeishuConfig } from '@/api/feishu'
import { getSubAccounts, patchSubAccountFundParams } from '@/api/accounts'
import { getAccountBalance, manualTransfer, crossAccountTransfer } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'
import { extractError } from '@/api/client'

interface SubAccount {
  id: number
  note: string
  email: string
  bnb_burn_enabled: boolean
  bnb_interest_enabled: boolean
  order_amount: string | null
  base_margin_amount: string | null
  single_transfer_amount: string | null
  risk_threshold: string | null
  min_balance: string | null
  single_order_amount: string | null
  max_positions: number | null
  max_borrow_amount: string | null
  borrow_rate_per_sec: string | null
}

interface AccountBalance {
  spot_usdt_free: string
  spot_usdt_locked: string
  funding_usdt: string
  earn_total: string
  margin_level: string
  margin_usdt_free: string
  margin_usdt_borrowed: string
  futures_total_balance: string
  futures_available: string
  futures_unrealized_pnl: string
  bnb_free: string
  bnb_interest: string
}

type WalletType = 'spot' | 'futures' | 'margin'

const WALLET_LABELS: Record<WalletType, string> = {
  spot: '现货',
  futures: '合约',
  margin: '全仓',
}

const TRANSFER_OPTIONS = [
  { value: 'futures,spot,margin', label: '合约 > 现货 > 全仓' },
  { value: 'futures,margin,spot', label: '合约 > 全仓 > 现货' },
  { value: 'spot,futures,margin', label: '现货 > 合约 > 全仓' },
  { value: 'spot,margin,futures', label: '现货 > 全仓 > 合约' },
  { value: 'margin,futures,spot', label: '全仓 > 合约 > 现货' },
  { value: 'margin,spot,futures', label: '全仓 > 现货 > 合约' },
]

function getWalletBalance(bal: AccountBalance | undefined, wallet: WalletType): number {
  if (!bal) return 0
  switch (wallet) {
    case 'spot': return parseFloat(bal.spot_usdt_free) || 0
    case 'futures': return parseFloat(bal.futures_available) || 0
    case 'margin': return parseFloat(bal.margin_usdt_free) || 0
  }
}

function InlineField({
  label,
  value,
  onChange,
  suffix,
  prefix,
  width = 'w-12',
}: {
  label?: string
  value: string | number
  onChange: (v: string) => void
  suffix?: string
  prefix?: string
  width?: string
}) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px]">
      {prefix && <span className="text-muted-foreground">{prefix}</span>}
      {label && <span className="text-muted-foreground">{label}</span>}
      <input
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className={`${width} bg-transparent border-b border-border text-center text-foreground font-mono tabular-nums text-[11px] focus:outline-none focus:border-primary py-0.5`}
      />
      {suffix && <span className="text-muted-foreground">{suffix}</span>}
    </span>
  )
}

function TogglePill({
  label,
  active,
  onChange,
}: {
  label: string
  active: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      onClick={() => onChange(!active)}
      className={`px-3 py-1 rounded text-[11px] font-medium border transition-colors ${
        active
          ? 'bg-primary/20 text-primary border-primary/30'
          : 'bg-[#1a1a22] text-muted-foreground border-border'
      }`}
    >
      {label}
    </button>
  )
}

function EditableCell({
  accountId,
  field,
  value,
  editingCells,
  setEditingCells,
  onSave,
}: {
  accountId: number
  field: string
  value: string | null
  editingCells: Record<string, string>
  setEditingCells: (c: Record<string, string>) => void
  onSave: (id: number, field: string, value: string) => void
}) {
  const key = `${accountId}-${field}`
  const editing = key in editingCells

  if (editing) {
    return (
      <td className="px-1.5 py-0.5 text-right">
        <input
          autoFocus
          value={editingCells[key]}
          onChange={(e) => setEditingCells({ ...editingCells, [key]: e.target.value })}
          onBlur={() => {
            onSave(accountId, field, editingCells[key])
            const next = { ...editingCells }
            delete next[key]
            setEditingCells(next)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onSave(accountId, field, editingCells[key])
              const next = { ...editingCells }
              delete next[key]
              setEditingCells(next)
            }
            if (e.key === 'Escape') {
              const next = { ...editingCells }
              delete next[key]
              setEditingCells(next)
            }
          }}
          className="w-14 bg-[#1a1a22] border border-primary rounded px-1 py-0.5 text-[11px] text-foreground text-right focus:outline-none"
        />
      </td>
    )
  }

  return (
    <td
      className="px-1.5 py-1 text-right font-mono cursor-pointer hover:bg-primary/10"
      onClick={() => setEditingCells({ ...editingCells, [key]: value ?? '' })}
    >
      {value ?? <span className="text-muted-foreground">-</span>}
    </td>
  )
}

type TransferMode = 'internal' | 'cross'

function TransferModal({
  account,
  balance,
  accounts,
  balances,
  onClose,
  onSuccess,
}: {
  account: SubAccount
  balance: AccountBalance | undefined
  accounts: SubAccount[]
  balances: Record<number, AccountBalance>
  onClose: () => void
  onSuccess: () => void
}) {
  const [mode, setMode] = useState<TransferMode>('internal')
  const [fromWallet, setFromWallet] = useState<WalletType>('futures')
  const [toWallet, setToWallet] = useState<WalletType>('margin')
  const [amount, setAmount] = useState('')
  const [transferring, setTransferring] = useState(false)
  const [targetType, setTargetType] = useState<'master' | 'sub'>('master')
  const [targetSubId, setTargetSubId] = useState<number>(0)
  const addToast = useToastStore((s) => s.addToast)

  const wallets: WalletType[] = ['spot', 'futures', 'margin']

  const selectFrom = (w: WalletType) => {
    setFromWallet(w)
    if (w === toWallet) {
      const alt = wallets.find((t) => t !== w)
      if (alt) setToWallet(alt)
    }
  }

  const handleInternalTransfer = async () => {
    const num = parseFloat(amount)
    if (!num || num <= 0) { addToast('请输入有效金额', 'error'); return }
    setTransferring(true)
    try {
      await manualTransfer(account.id, {
        from_wallet: fromWallet, to_wallet: toWallet, asset: 'USDT', amount: num,
      })
      addToast(`划转成功: ${WALLET_LABELS[fromWallet]} → ${WALLET_LABELS[toWallet]} ${num} USDT`, 'success')
      onSuccess(); onClose()
    } catch (err: unknown) {
      addToast(extractError(err, '划转失败'), 'error')
    }
    setTransferring(false)
  }

  const handleCrossTransfer = async () => {
    const num = parseFloat(amount)
    if (!num || num <= 0) { addToast('请输入有效金额', 'error'); return }
    if (targetType === 'sub' && !targetSubId) { addToast('请选择目标子账户', 'error'); return }
    setTransferring(true)
    try {
      await crossAccountTransfer(account.id, {
        target_type: targetType,
        target_sub_account_id: targetType === 'sub' ? targetSubId : undefined,
        asset: 'USDT',
        amount: num,
      })
      const targetLabel = targetType === 'master'
        ? '主账户'
        : accounts.find((a) => a.id === targetSubId)?.note || `#${targetSubId}`
      addToast(`划转成功: ${account.note} → ${targetLabel} ${num} USDT`, 'success')
      onSuccess(); onClose()
    } catch (err: unknown) {
      addToast(extractError(err, '划转失败'), 'error')
    }
    setTransferring(false)
  }

  const validToWallets = wallets.filter((w) => w !== fromWallet)
  const otherAccounts = accounts.filter((a) => a.id !== account.id)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-[#0d0d14] border border-border rounded-lg w-[calc(100vw-2rem)] max-w-[420px] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header with mode tabs */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMode('internal')}
              className={`text-sm font-semibold pb-0.5 transition-colors ${
                mode === 'internal' ? 'text-foreground border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              内部划转
            </button>
            <button
              onClick={() => setMode('cross')}
              className={`text-sm font-semibold pb-0.5 transition-colors ${
                mode === 'cross' ? 'text-foreground border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              跨账户划转
            </button>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-lg leading-none">✕</button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Current account */}
          <div className="text-[13px]">
            <span className="text-muted-foreground">当前账户: </span>
            <span className="text-foreground font-medium">{account.note} | {account.email}</span>
          </div>

          {mode === 'internal' ? (
            <>
              {/* From wallet selector */}
              <div className="space-y-1.5">
                <span className="text-[12px] text-muted-foreground font-medium">划出账号</span>
                <div className="flex rounded-lg overflow-hidden border border-border">
                  {wallets.map((w) => {
                    const bal = getWalletBalance(balance, w)
                    const selected = fromWallet === w
                    return (
                      <button
                        key={w}
                        onClick={() => selectFrom(w)}
                        className={`flex-1 py-3 text-center transition-colors ${
                          selected ? 'bg-primary text-white' : 'bg-[#1a1a22] text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        <div className="text-[12px] font-medium">{WALLET_LABELS[w]}</div>
                        <div className={`text-[15px] font-mono tabular-nums font-bold mt-0.5 ${selected ? 'text-white' : 'text-foreground'}`}>
                          {Math.round(bal)}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Transfer direction button */}
              <div className="flex justify-center">
                <button
                  onClick={() => { const prev = fromWallet; setFromWallet(toWallet); setToWallet(prev) }}
                  className="w-9 h-9 rounded-full border border-primary/50 bg-primary/10 flex items-center justify-center text-primary hover:bg-primary/20 transition-colors"
                  title="交换方向"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7 16V4m0 0L3 8m4-4l4 4" />
                    <path d="M17 8v12m0 0l4-4m-4 4l-4-4" />
                  </svg>
                </button>
              </div>

              {/* To wallet selector */}
              <div className="space-y-1.5">
                <span className="text-[12px] text-muted-foreground font-medium">划入账号</span>
                <div className="flex rounded-lg overflow-hidden border border-border">
                  {validToWallets.map((w) => {
                    const bal = getWalletBalance(balance, w)
                    const selected = toWallet === w
                    return (
                      <button
                        key={w}
                        onClick={() => setToWallet(w)}
                        className={`flex-1 py-3 text-center transition-colors ${
                          selected ? 'bg-primary/20 text-primary border border-primary/30' : 'bg-[#1a1a22] text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        <div className="text-[12px] font-medium">{WALLET_LABELS[w]}</div>
                        <div className={`text-[15px] font-mono tabular-nums font-bold mt-0.5 ${selected ? 'text-primary' : 'text-foreground'}`}>
                          {Math.round(bal)}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Amount + Transfer button */}
              <div className="flex items-center gap-3 pt-1">
                <span className="text-[13px] text-muted-foreground font-medium shrink-0">划转金额</span>
                <input
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="flex-1 bg-[#1a1a22] border border-border rounded-lg px-3 py-2.5 text-[13px] text-foreground font-mono focus:outline-none focus:border-primary"
                  placeholder="输入金额"
                />
                <button
                  onClick={handleInternalTransfer}
                  disabled={transferring}
                  className="px-6 py-2.5 rounded-lg text-[13px] font-medium bg-primary text-white hover:bg-primary/80 disabled:opacity-40 shrink-0"
                >
                  {transferring ? '划转中...' : '划转'}
                </button>
              </div>
            </>
          ) : (
            <>
              {/* Target type selector */}
              <div className="space-y-1.5">
                <span className="text-[12px] text-muted-foreground font-medium">划转目标</span>
                <div className="flex rounded-lg overflow-hidden border border-border">
                  <button
                    onClick={() => setTargetType('master')}
                    className={`flex-1 py-2.5 text-center text-[12px] font-medium transition-colors ${
                      targetType === 'master' ? 'bg-primary text-white' : 'bg-[#1a1a22] text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    主账户
                  </button>
                  <button
                    onClick={() => setTargetType('sub')}
                    className={`flex-1 py-2.5 text-center text-[12px] font-medium transition-colors ${
                      targetType === 'sub' ? 'bg-primary text-white' : 'bg-[#1a1a22] text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    其他子账户
                  </button>
                </div>
              </div>

              {/* Direction visualization */}
              <div className="flex items-center justify-center gap-3 text-[13px] py-1">
                <span className="px-3 py-1.5 rounded border border-primary/30 bg-primary/10 text-primary font-medium">{account.note}</span>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary">
                  <path d="M5 12h14m0 0l-4-4m4 4l-4 4" />
                </svg>
                {targetType === 'master' ? (
                  <span className="px-3 py-1.5 rounded border border-positive/30 bg-positive/10 text-positive font-medium">主账户</span>
                ) : (
                  <select
                    value={targetSubId}
                    onChange={(e) => setTargetSubId(Number(e.target.value))}
                    className="bg-[#1a1a22] border border-border rounded-lg px-3 py-1.5 text-[13px] text-foreground focus:outline-none focus:border-primary"
                  >
                    <option value={0}>选择子账户</option>
                    {otherAccounts.map((a) => {
                      const b = balances[a.id]
                      const total = b ? Math.round(parseFloat(b.spot_usdt_free) + parseFloat(b.margin_usdt_free) + parseFloat(b.futures_available)) : 0
                      return (
                        <option key={a.id} value={a.id}>
                          {a.note} ({a.email}) — {total} U
                        </option>
                      )
                    })}
                  </select>
                )}
              </div>

              {/* Source account balance summary */}
              <div className="text-[11px] text-muted-foreground bg-[#1a1a22] rounded p-2.5 flex items-center gap-4">
                <span>现货: <span className="text-foreground font-mono">{balance ? Math.round(parseFloat(balance.spot_usdt_free)) : 0}</span></span>
                <span>全仓: <span className="text-foreground font-mono">{balance ? Math.round(parseFloat(balance.margin_usdt_free)) : 0}</span></span>
                <span>合约: <span className="text-foreground font-mono">{balance ? Math.round(parseFloat(balance.futures_available)) : 0}</span></span>
              </div>

              {/* Amount + Transfer button */}
              <div className="flex items-center gap-3 pt-1">
                <span className="text-[13px] text-muted-foreground font-medium shrink-0">划转金额</span>
                <input
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="flex-1 bg-[#1a1a22] border border-border rounded-lg px-3 py-2.5 text-[13px] text-foreground font-mono focus:outline-none focus:border-primary"
                  placeholder="输入金额"
                />
                <button
                  onClick={handleCrossTransfer}
                  disabled={transferring}
                  className="px-6 py-2.5 rounded-lg text-[13px] font-medium bg-primary text-white hover:bg-primary/80 disabled:opacity-40 shrink-0"
                >
                  {transferring ? '划转中...' : '划转'}
                </button>
              </div>

              <p className="text-[10px] text-muted-foreground/60">
                {targetType === 'master' ? '从子账户现货钱包划转到主账户' : '通过主账户中转，从现货钱包到现货钱包'}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export function RulesPage() {
  const navigate = useNavigate()
  const [feishu, setFeishu] = useState<Record<string, unknown>>({})
  const [globalRules, setGlobalRules] = useState<Record<string, unknown>>({})
  const [fundRules, setFundRules] = useState<Record<string, unknown>>({})
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [balances, setBalances] = useState<Record<number, AccountBalance>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [editingCells, setEditingCells] = useState<Record<string, string>>({})
  const [maxBorrowToggle, setMaxBorrowToggle] = useState(() => {
    try { return localStorage.getItem('hc_borrow_display_mode') === 'usdt' } catch { return false }
  })
  const [transferAccount, setTransferAccount] = useState<SubAccount | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const fetchAll = useCallback(() => {
    setLoading(true)
    Promise.all([
      getFeishuConfig().then(setFeishu).catch(() => {}),
      getGlobalRules().then(setGlobalRules).catch(() => {}),
      getFundRules().then(setFundRules).catch(() => {}),
      getSubAccounts().then(setAccounts).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const fetchBalances = useCallback(() => {
    if (accounts.length === 0) return
    accounts.forEach((a) => {
      getAccountBalance(a.id).then((b) => {
        setBalances((prev) => ({ ...prev, [a.id]: b }))
      }).catch(() => {})
    })
  }, [accounts])

  useEffect(() => { fetchBalances() }, [fetchBalances])

  const updateF = (key: string, val: string) => setFeishu((p) => ({ ...p, [key]: val }))
  const updateFBool = (key: string, val: boolean) => setFeishu((p) => ({ ...p, [key]: val }))
  const updateG = (key: string, val: string) => setGlobalRules((p) => ({ ...p, [key]: val }))
  const updateFR = (key: string, val: string) => setFundRules((p) => ({ ...p, [key]: val }))

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await Promise.all([
        updateFeishuConfig(feishu),
        updateGlobalRules(globalRules),
        updateFundRules(fundRules),
      ])
      addToast('保存成功', 'success')
    } catch (err: unknown) {
      addToast(extractError(err, '保存失败'), 'error')
    }
    setSaving(false)
  }, [feishu, globalRules, fundRules, addToast])

  const handleTest = useCallback(async () => {
    setTesting(true)
    try {
      await testFeishuConfig()
      addToast('测试消息已发送', 'success')
    } catch (err: unknown) {
      addToast(extractError(err, '发送失败'), 'error')
    }
    setTesting(false)
  }, [addToast])

  const handleFundParamSave = useCallback(async (accountId: number, field: string, value: string) => {
    try {
      await patchSubAccountFundParams(accountId, { [field]: value || null })
      addToast('已保存', 'success')

      // E1: 30% linkage — when single_order_amount changes, ensure min_balance >= 30%
      if (field === 'single_order_amount' && value) {
        const orderAmt = parseFloat(value)
        if (!isNaN(orderAmt) && orderAmt > 0) {
          const minRequired = Math.ceil(orderAmt * 0.3)
          const account = accounts.find(a => a.id === accountId)
          const currentMin = parseFloat(account?.min_balance || '0') || 0
          if (currentMin < minRequired) {
            await patchSubAccountFundParams(accountId, { min_balance: String(minRequired) })
            setAccounts(prev => prev.map(a =>
              a.id === accountId ? { ...a, single_order_amount: value, min_balance: String(minRequired) } : a,
            ))
            addToast(`保底额已自动调整为 ${minRequired} (挂单单笔的30%)`, 'info')
            return
          }
        }
      }

      setAccounts(prev => prev.map(a =>
        a.id === accountId ? { ...a, [field]: value || null } : a,
      ))
    } catch (err: unknown) {
      addToast(extractError(err, '保存失败'), 'error')
    }
  }, [addToast, accounts])

  const totalMarginFree = accounts.reduce((s, a) => {
    const b = balances[a.id]
    return s + (b ? parseFloat(b.margin_usdt_free) || 0 : 0)
  }, 0)

  const totalFuturesAvail = accounts.reduce((s, a) => {
    const b = balances[a.id]
    return s + (b ? parseFloat(b.futures_available) || 0 : 0)
  }, 0)

  const totalSpotFree = accounts.reduce((s, a) => {
    const b = balances[a.id]
    return s + (b ? parseFloat(b.spot_usdt_free) || 0 : 0)
  }, 0)

  if (loading) {
    return <p className="py-8 text-center text-muted-foreground text-xs">加载中...</p>
  }

  const strip = (v: unknown) => {
    const s = String(v ?? '')
    if (s && s.includes('.')) return s.replace(/\.?0+$/, '')
    return s
  }

  const fv = (key: string) => strip(feishu[key])
  const gv = (key: string) => strip(globalRules[key])
  const frv = (key: string) => strip(fundRules[key])

  const bnbIntervalMin = Math.round((parseFloat(frv('bnb_convert_interval_sec')) || 0) / 60)
  const debtIntervalHr = Math.round((parseFloat(frv('debt_convert_interval_sec')) || 0) / 3600)

  return (
    <div className="h-full bg-background flex flex-col overflow-hidden">
      {/* Title bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#0d0d14] border-b border-border shrink-0">
        <span className="text-sm font-semibold">规则设置</span>
        <button
          onClick={() => navigate('/dashboard')}
          className="text-muted-foreground hover:text-foreground text-lg leading-none px-1"
        >
          ✕
        </button>
      </div>

      {/* Two-column body */}
      <div className="flex flex-col md:flex-row gap-4 p-3 flex-1 overflow-auto min-h-0">
        {/* ====== LEFT COLUMN ====== */}
        <div className="w-full md:w-[56%] space-y-3 md:shrink-0">
          {/* -- Feishu Alert Config -- */}
          <div className="space-y-2 bg-[#111118] rounded border border-border p-3">
            <div className="flex items-center gap-4 flex-wrap">
              <InlineField label="提醒间隔" value={fv('alert_interval_sec')} onChange={(v) => updateF('alert_interval_sec', v)} suffix="秒" />
              <InlineField label="提醒次数" value={fv('alert_count')} onChange={(v) => updateF('alert_count', v)} />
              <button
                onClick={handleTest}
                disabled={testing}
                className="px-3 py-1 rounded text-[11px] font-medium bg-primary text-white hover:bg-primary/80 disabled:opacity-40"
              >
                {testing ? '发送中...' : '测试'}
              </button>
            </div>
            <div className="flex items-center gap-4 flex-wrap">
              <InlineField label="合约爆仓率提醒 <" value={fv('margin_rate_alert')} onChange={(v) => updateF('margin_rate_alert', v)} suffix="%" width="w-10" />
              <InlineField label="杠杆风险率提醒 <" value={fv('leverage_risk_alert')} onChange={(v) => updateF('leverage_risk_alert', v)} width="w-12" />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <TogglePill label="划转失败提醒" active={!!feishu.enable_transfer_fail_alert} onChange={(v) => updateFBool('enable_transfer_fail_alert', v)} />
              <TogglePill label="新增借币提醒" active={!!feishu.enable_new_borrow_alert} onChange={(v) => updateFBool('enable_new_borrow_alert', v)} />
              <TogglePill label="最大可借金额" active={maxBorrowToggle} onChange={(v) => {
                setMaxBorrowToggle(v)
                try { localStorage.setItem('hc_borrow_display_mode', v ? 'usdt' : 'qty') } catch { /* ignore */ }
              }} />
            </div>
          </div>

          {/* -- Auto Transfer -- */}
          <div className="border border-positive/50 rounded p-2.5 bg-[#111118] space-y-1.5">
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-positive font-medium">自动划转:</span>
              <select
                value={frv('transfer_order')}
                onChange={(e) => updateFR('transfer_order', e.target.value)}
                className="bg-transparent text-positive border-none text-[11px] font-medium focus:outline-none cursor-pointer"
              >
                {TRANSFER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value} className="bg-[#1a1a22] text-foreground">{o.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-5 text-[11px]">
              <span className="text-muted-foreground">全仓可转: <span className="text-foreground font-mono tabular-nums">{Math.round(totalMarginFree)}</span></span>
              <span className="text-muted-foreground">合约可转: <span className="text-foreground font-mono tabular-nums">{Math.round(totalFuturesAvail)}</span></span>
              <span className="text-muted-foreground">现货可转: <span className="text-foreground font-mono tabular-nums">{Math.round(totalSpotFree)}</span></span>
            </div>
          </div>

          {/* -- Sub-Account Table -- */}
          <div className="bg-[#111118] rounded border border-border overflow-x-auto">
            <table className="w-full min-w-[750px] text-[11px] border-collapse">
              <thead>
                <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                  <th className="px-1.5 py-1.5 text-left font-medium">备注</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">BNB</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">BNB息</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">U借</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">保</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">可</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">可转</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">风险</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">风控阈</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">单笔划</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">保底额</th>
                  <th className="px-1.5 py-1.5 text-right font-medium">挂单单笔</th>
                  <th className="px-1.5 py-1.5 text-right font-medium" title="每账户借币金额上限(USDT,=maxBorrowable 封顶)，留空跟随全局">金额限制</th>
                  <th className="px-1.5 py-1.5 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => {
                  const bal = balances[a.id]
                  return (
                    <tr key={a.id} className="border-b border-border/30 hover:bg-[#1a1a22]/60">
                      <td className="px-1.5 py-1 font-medium">{a.note}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? parseFloat(bal.bnb_free).toFixed(2) : '-'}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? parseFloat(bal.bnb_interest).toFixed(4) : '-'}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? parseFloat(bal.margin_usdt_borrowed).toFixed(2) : '-'}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? Math.round(parseFloat(bal.futures_total_balance)) : '-'}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? Math.round(parseFloat(bal.futures_available)) : '-'}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? Math.round(parseFloat(bal.margin_usdt_free)) : '-'}</td>
                      <td className="px-1.5 py-1 text-right font-mono tabular-nums">{bal ? parseFloat(bal.margin_level).toFixed(2) : '-'}</td>
                      <EditableCell accountId={a.id} field="risk_threshold" value={a.risk_threshold} editingCells={editingCells} setEditingCells={setEditingCells} onSave={handleFundParamSave} />
                      <EditableCell accountId={a.id} field="single_transfer_amount" value={a.single_transfer_amount} editingCells={editingCells} setEditingCells={setEditingCells} onSave={handleFundParamSave} />
                      <EditableCell accountId={a.id} field="min_balance" value={a.min_balance} editingCells={editingCells} setEditingCells={setEditingCells} onSave={handleFundParamSave} />
                      <EditableCell accountId={a.id} field="single_order_amount" value={a.single_order_amount} editingCells={editingCells} setEditingCells={setEditingCells} onSave={handleFundParamSave} />
                      <EditableCell accountId={a.id} field="max_borrow_amount" value={a.max_borrow_amount} editingCells={editingCells} setEditingCells={setEditingCells} onSave={handleFundParamSave} />
                      <td className="px-1.5 py-1 text-center">
                        <button
                          onClick={() => setTransferAccount(a)}
                          className="px-2 py-0.5 rounded text-[10px] bg-primary/20 text-primary hover:bg-primary/30"
                        >
                          划转
                        </button>
                      </td>
                    </tr>
                  )
                })}
                {accounts.length === 0 && (
                  <tr><td colSpan={14} className="px-2 py-4 text-center text-muted-foreground">无子账户</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* ====== RIGHT COLUMN ====== */}
        <div className="flex-1 space-y-3 min-w-0">
          {/* -- BNB Management -- */}
          <div className="bg-[#111118] rounded border border-border p-3 space-y-2.5">
            <div className="flex items-center flex-wrap gap-1 text-[11px]">
              <span className="text-muted-foreground">全仓BNB抵扣手续费数量</span>
              <InlineField value={frv('bnb_min_quantity')} onChange={(v) => updateFR('bnb_min_quantity', v)} width="w-10" />
              <span className="text-muted-foreground">低于设定的</span>
              <InlineField value={frv('bnb_buy_trigger_pct')} onChange={(v) => updateFR('bnb_buy_trigger_pct', v)} width="w-8" />
              <span className="text-muted-foreground">%买</span>
              <InlineField value={frv('bnb_buy_amount')} onChange={(v) => updateFR('bnb_buy_amount', v)} width="w-8" />
              <span className="text-muted-foreground">个(3秒)</span>
            </div>
            <div className="flex items-center flex-wrap gap-1 text-[11px]">
              <span className="text-muted-foreground">全仓BNB欠款自动还款当大于</span>
              <InlineField value={frv('bnb_debt_threshold')} onChange={(v) => updateFR('bnb_debt_threshold', v)} width="w-10" />
              <span className="text-muted-foreground ml-2">买入并还款(1小时)</span>
            </div>
            <div className="flex items-center flex-wrap gap-1 text-[11px]">
              <span className="text-muted-foreground">全仓USDT欠款自动还款当大于</span>
              <InlineField value={frv('usdt_debt_threshold')} onChange={(v) => updateFR('usdt_debt_threshold', v)} width="w-10" />
              <span className="text-muted-foreground ml-2">执行还款(1小时)</span>
            </div>
            <div className="flex items-center flex-wrap gap-3 text-[11px]">
              <span className="text-muted-foreground">全仓小额兑换BNB间隔</span>
              <InlineField
                value={bnbIntervalMin}
                onChange={(v) => updateFR('bnb_convert_interval_sec', String((parseFloat(v) || 0) * 60))}
                suffix="分钟"
                width="w-10"
              />
              <span className="text-muted-foreground">全仓负债转换间隔</span>
              <InlineField
                value={debtIntervalHr}
                onChange={(v) => updateFR('debt_convert_interval_sec', String((parseFloat(v) || 0) * 3600))}
                suffix="小时"
                width="w-8"
              />
            </div>
          </div>

          {/* -- Trading Parameters -- */}
          <div className="bg-[#111118] rounded border border-border p-3 space-y-2.5">
            <div className="flex items-center gap-6 flex-wrap text-[11px]">
              <InlineField label="自动推送点差" value={gv('auto_push_spread')} onChange={(v) => updateG('auto_push_spread', v)} width="w-10" />
              <InlineField label="日利息拦截" value={gv('interest_filter')} onChange={(v) => updateG('interest_filter', v)} suffix="%" width="w-10" />
            </div>
            <div className="flex items-center gap-3 flex-wrap text-[11px]">
              <InlineField label="推送二次确认" value={gv('confirm_delay_sec')} onChange={(v) => updateG('confirm_delay_sec', v)} suffix="秒" width="w-8" />
              <span className="text-muted-foreground">点差≥</span>
              <InlineField value={gv('confirm_skip_spread')} onChange={(v) => updateG('confirm_skip_spread', v)} width="w-8" />
              <span className="text-muted-foreground">直接推送(不二次确认)</span>
            </div>
            <div className="flex items-center gap-6 flex-wrap text-[11px]">
              <InlineField label="点差不足移除" value={gv('remove_spread')} onChange={(v) => updateG('remove_spread', v)} width="w-10" />
              <InlineField label="手动移除尾单清理金额" value={gv('max_loss_per_position')} onChange={(v) => updateG('max_loss_per_position', v)} suffix="U" width="w-10" />
            </div>
            <div className="flex items-center gap-4 flex-wrap text-[11px]">
              <InlineField label="挂单点差" value={gv('borrow_spread')} onChange={(v) => updateG('borrow_spread', v)} width="w-10" />
              <InlineField label="开仓点差" value={gv('open_spread')} onChange={(v) => updateG('open_spread', v)} width="w-10" />
              <InlineField label="单笔下单额" value={gv('order_amount')} onChange={(v) => updateG('order_amount', v)} width="w-10" />
              <InlineField label="借币延迟开仓" value={gv('borrow_delay_sec')} onChange={(v) => updateG('borrow_delay_sec', v)} suffix="秒" width="w-8" />
            </div>
            <div className="flex items-center gap-6 flex-wrap text-[11px]">
              <InlineField label="平仓点差" value={gv('close_spread')} onChange={(v) => updateG('close_spread', v)} width="w-10" />
              <span className="text-muted-foreground">平仓: 资息倍率 &lt;</span>
              <InlineField value={gv('close_funding_ratio')} onChange={(v) => updateG('close_funding_ratio', v)} width="w-10" />
            </div>
            <div className="flex items-center gap-4 flex-wrap text-[11px]">
              <span className="text-muted-foreground">自动还币开仓点差 &lt;</span>
              <InlineField value={gv('repay_spread')} onChange={(v) => updateG('repay_spread', v)} width="w-10" />
              <span className="text-muted-foreground">还币: 资息倍率 &lt;</span>
              <InlineField value={gv('repay_funding_ratio')} onChange={(v) => updateG('repay_funding_ratio', v)} width="w-10" />
            </div>
            {/* 下单质量(高级) — 桌面参数对齐 */}
            <div className="flex items-center gap-4 flex-wrap text-[11px] pt-1 border-t border-border/40">
              <span className="text-muted-foreground/70 text-[10px]">下单质量(高级)</span>
              <div className="flex items-center gap-1">
                <span className="text-muted-foreground">跟单方式</span>
                <select
                  value={(gv('follow_type') || 'market')}
                  onChange={(e) => updateG('follow_type', e.target.value)}
                  className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
                >
                  <option value="market">市价</option>
                  <option value="limit">限价</option>
                </select>
              </div>
              <InlineField label="滑点" value={gv('slippage_pct')} onChange={(v) => updateG('slippage_pct', v)} suffix="%" width="w-10" />
              <InlineField label="现货成交后等待" value={gv('stabilize_sec')} onChange={(v) => updateG('stabilize_sec', v)} suffix="秒" width="w-8" />
              <InlineField label="分层建仓" value={gv('tier_ratios')} onChange={(v) => updateG('tier_ratios', v)} width="w-28" />
            </div>
            {/* 限流：每账户借币配速 */}
            <div className="flex items-center gap-2 flex-wrap text-[11px]">
              <span className="text-muted-foreground/70 text-[10px]">限流</span>
              <InlineField label="每账户借币速率" value={gv('borrow_rate_per_sec')} onChange={(v) => updateG('borrow_rate_per_sec', v)} suffix="次/秒" width="w-10" />
              <span className="text-muted-foreground/60 text-[10px]">单 UID 硬顶 2/秒(180000÷1500)；多账户聚合 = 本值×账户数</span>
            </div>
            {/* 借币方式：IOC OTOCO 开关 + 撤单腿数 */}
            <div className="flex items-center gap-2 flex-wrap text-[11px]">
              <span className="text-muted-foreground/70 text-[10px]">借币方式</span>
              <button
                onClick={() => setGlobalRules((p) => ({ ...p, borrow_via_otoco: !(p.borrow_via_otoco === true || p.borrow_via_otoco === 'true') }))}
                className={`px-2 py-0.5 rounded text-[11px] ${(globalRules.borrow_via_otoco === true || globalRules.borrow_via_otoco === 'true') ? 'bg-positive/20 text-positive' : 'bg-accent text-muted-foreground'}`}
              >
                {(globalRules.borrow_via_otoco === true || globalRules.borrow_via_otoco === 'true') ? 'IOC OTOCO 挂单借币' : 'borrow-repay 直接借'}
              </button>
              <span className="text-muted-foreground/70 text-[10px]">撤单腿数</span>
              <select
                value={String(globalRules.otoco_legs ?? 2)}
                onChange={(e) => setGlobalRules((p) => ({ ...p, otoco_legs: Number(e.target.value) }))}
                className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
              >
                <option value="2">2 单 (OTO)</option>
                <option value="3">3 单 (OTOCO)</option>
              </select>
              <span className="text-muted-foreground/60 text-[10px]">开启=coinmini 同款 IOC 挂单借币;2 单撤单更省、反滥用压力更低</span>
            </div>
            <div className="text-[10px] text-muted-foreground/60 -mt-1">
              限价：合约腿用可成交限价(挂价≥卖一×(1+滑点))封顶滑点，超时未成交自动市价补齐——永不留敞口。分层格式「偏移%:数量%」如 0.5:30,0.8:30,1.2:40。受控测试请先用小额单笔下单额验证。
            </div>

            <div className="flex items-center justify-between flex-wrap text-[11px]">
              <div className="flex items-center gap-1">
                <span className="text-muted-foreground">首次借币后</span>
                <InlineField value={gv('repay_ban_minutes')} onChange={(v) => updateG('repay_ban_minutes', v)} width="w-10" />
                <span className="text-muted-foreground">分钟内禁止自动还币</span>
              </div>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-5 py-1.5 rounded text-[12px] font-medium bg-primary text-white hover:bg-primary/80 disabled:opacity-40"
              >
                {saving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Transfer Modal */}
      {transferAccount && (
        <TransferModal
          account={transferAccount}
          balance={balances[transferAccount.id]}
          accounts={accounts}
          balances={balances}
          onClose={() => setTransferAccount(null)}
          onSuccess={fetchBalances}
        />
      )}
    </div>
  )
}
