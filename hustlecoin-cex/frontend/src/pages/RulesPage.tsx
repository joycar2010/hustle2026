import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getGlobalRules, getFundRules, saveAllRules } from '@/api/rules'
import { getFeishuConfig, testFeishuConfig } from '@/api/feishu'
import { getSubAccounts, patchSubAccountFundParams, getMasterBalance } from '@/api/accounts'
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
  muted = false,
  title,
}: {
  label?: string
  value: string | number
  onChange: (v: string) => void
  suffix?: string
  prefix?: string
  width?: string
  muted?: boolean      // true=该项未接入引擎,整体灰显 + tooltip 说明(防运营误判)
  title?: string
}) {
  // muted 项:文字/输入框统一压到 40% 透明度,鼠标悬停看 title 说明;不改任何保存/绑定逻辑
  const labelCls = muted ? 'text-muted-foreground/40' : 'text-muted-foreground'
  const inputCls = muted ? 'opacity-40' : ''
  // 本地输入缓冲:保留用户原始按键(含中间态的尾零/前导零),避免外层 strip(去尾零)在输入途中
  // 把 "0.10"→"0.1"、"0.00"→"0" 截断 —— 那会导致 0.00X 这类4位小数根本打不进去。
  // 仅当外部值「数值上」真的变了(非尾零差异)才回灌(外部加载/重置/保存后刷新)。
  const [local, setLocal] = useState<string>(String(value ?? ''))
  useEffect(() => {
    const ext = String(value ?? '')
    setLocal((cur) => {
      if (ext === cur) return cur
      const a = parseFloat(ext), b = parseFloat(cur)
      if (!Number.isNaN(a) && a === b) return cur   // 0.1≡0.10、0≡0.00 → 不打断输入
      return ext
    })
  }, [value])
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] ${muted ? 'cursor-help' : ''}`} title={title}>
      {prefix && <span className={labelCls}>{prefix}</span>}
      {label && <span className={labelCls}>{label}{muted ? '*' : ''}</span>}
      <input
        value={local}
        onChange={(e) => { setLocal(e.target.value); onChange(e.target.value) }}
        className={`${width} bg-transparent border-b border-border text-center text-foreground font-mono tabular-nums text-[11px] focus:outline-none focus:border-primary py-0.5 ${inputCls}`}
      />
      {suffix && <span className={labelCls}>{suffix}</span>}
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
  dirty,
  editingCells,
  setEditingCells,
  onSave,
}: {
  accountId: number
  field: string
  value: string | null
  dirty?: boolean
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
      className={`px-1.5 py-1 text-right font-mono cursor-pointer hover:bg-primary/10 ${dirty ? 'text-amber-400 bg-amber-400/5' : ''}`}
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
  const [crossDir, setCrossDir] = useState<'out' | 'in'>('out')   // out=本账户转出, in=本账户转入
  const [crossFromWallet, setCrossFromWallet] = useState<WalletType>('spot')
  const [crossToWallet, setCrossToWallet] = useState<WalletType>('spot')
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
    if (targetType === 'sub' && !targetSubId) { addToast('请选择对手子账户', 'error'); return }
    setTransferring(true)
    try {
      await crossAccountTransfer(account.id, {
        direction: crossDir,
        counterparty_type: targetType,
        counterparty_sub_account_id: targetType === 'sub' ? targetSubId : undefined,
        from_wallet: crossFromWallet,
        to_wallet: crossToWallet,
        asset: 'USDT',
        amount: num,
      })
      const cpLabel = targetType === 'master'
        ? '主账户'
        : accounts.find((a) => a.id === targetSubId)?.note || `#${targetSubId}`
      const [src, dst] = crossDir === 'out' ? [account.note, cpLabel] : [cpLabel, account.note]
      addToast(`划转成功: ${src} → ${dst} ${num} USDT`, 'success')
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
              {/* 方向 + 对手账户 selectors */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <span className="text-[12px] text-muted-foreground font-medium">方向</span>
                  <div className="flex rounded-lg overflow-hidden border border-border">
                    <button
                      onClick={() => setCrossDir('out')}
                      className={`flex-1 py-2.5 text-center text-[12px] font-medium transition-colors ${
                        crossDir === 'out' ? 'bg-primary text-white' : 'bg-[#1a1a22] text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      本账户转出
                    </button>
                    <button
                      onClick={() => setCrossDir('in')}
                      className={`flex-1 py-2.5 text-center text-[12px] font-medium transition-colors ${
                        crossDir === 'in' ? 'bg-primary text-white' : 'bg-[#1a1a22] text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      本账户转入
                    </button>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <span className="text-[12px] text-muted-foreground font-medium">对手账户</span>
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
              </div>

              {targetType === 'sub' && (
                <select
                  value={targetSubId}
                  onChange={(e) => setTargetSubId(Number(e.target.value))}
                  className="w-full bg-[#1a1a22] border border-border rounded-lg px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-primary"
                >
                  <option value={0}>选择对手子账户</option>
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

              {/* Direction visualization (源 → 目标,随方向) */}
              {(() => {
                const cpLabel = targetType === 'master' ? '主账户'
                  : (otherAccounts.find((a) => a.id === targetSubId)?.note || '对手子账户')
                const [srcL, dstL] = crossDir === 'out' ? [account.note, cpLabel] : [cpLabel, account.note]
                return (
                  <div className="flex items-center justify-center gap-3 text-[13px] py-1">
                    <span className="px-3 py-1.5 rounded border border-primary/30 bg-primary/10 text-primary font-medium">{srcL}</span>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary">
                      <path d="M5 12h14m0 0l-4-4m4 4l-4 4" />
                    </svg>
                    <span className="px-3 py-1.5 rounded border border-positive/30 bg-positive/10 text-positive font-medium">{dstL}</span>
                  </div>
                )
              })()}

              {/* 源/目标 钱包 */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <span className="text-[12px] text-muted-foreground font-medium">源钱包</span>
                  <select
                    value={crossFromWallet}
                    onChange={(e) => setCrossFromWallet(e.target.value as WalletType)}
                    className="w-full bg-[#1a1a22] border border-border rounded-lg px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-primary"
                  >
                    {wallets.map((w) => <option key={w} value={w}>{WALLET_LABELS[w]}</option>)}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <span className="text-[12px] text-muted-foreground font-medium">目标钱包</span>
                  <select
                    value={crossToWallet}
                    onChange={(e) => setCrossToWallet(e.target.value as WalletType)}
                    className="w-full bg-[#1a1a22] border border-border rounded-lg px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-primary"
                  >
                    {wallets.map((w) => <option key={w} value={w}>{WALLET_LABELS[w]}</option>)}
                  </select>
                </div>
              </div>

              {/* 本账户余额 summary */}
              <div className="text-[11px] text-muted-foreground bg-[#1a1a22] rounded p-2.5 flex items-center gap-4">
                <span className="text-muted-foreground/60">{account.note}:</span>
                <span>现货 <span className="text-foreground font-mono">{balance ? Math.round(parseFloat(balance.spot_usdt_free)) : 0}</span></span>
                <span>全仓 <span className="text-foreground font-mono">{balance ? Math.round(parseFloat(balance.margin_usdt_free)) : 0}</span></span>
                <span>合约 <span className="text-foreground font-mono">{balance ? Math.round(parseFloat(balance.futures_available)) : 0}</span></span>
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
                经主账户万向划转(需主账户开启「万向划转」权限);主账户↔子账户、子账户↔子账户均可,源/目标钱包可选现货/全仓/合约。
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export function RulesPage({ onClose, embedded }: { onClose?: () => void; embedded?: boolean } = {}) {
  const navigate = useNavigate()
  const closeRules = () => { if (onClose) onClose(); else navigate('/dashboard') }
  const [feishu, setFeishu] = useState<Record<string, unknown>>({})
  const [globalRules, setGlobalRules] = useState<Record<string, unknown>>({})
  const [fundRules, setFundRules] = useState<Record<string, unknown>>({})
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [balances, setBalances] = useState<Record<number, AccountBalance>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [editingCells, setEditingCells] = useState<Record<string, string>>({})
  const [fundEdits, setFundEdits] = useState<Record<string, string>>({})   // 子账户资金参数暂存(批量确认前不落库)
  const [committingFund, setCommittingFund] = useState(false)
  const [maxBorrowToggle, setMaxBorrowToggle] = useState(() => {
    try { return localStorage.getItem('hc_borrow_display_mode') === 'usdt' } catch { return false }
  })
  const [transferAccount, setTransferAccount] = useState<SubAccount | null>(null)
  const [masterBalance, setMasterBalance] = useState<Record<string, string> | null>(null)  // 主账户余额(可转口径源)
  const addToast = useToastStore((s) => s.addToast)

  const fetchAll = useCallback(() => {
    setLoading(true)
    Promise.all([
      getFeishuConfig().then(setFeishu).catch(() => {}),
      getGlobalRules().then(setGlobalRules).catch(() => {}),
      getFundRules().then(setFundRules).catch(() => {}),
      getSubAccounts().then(setAccounts).catch(() => {}),
      getMasterBalance().then((b) => setMasterBalance(b as Record<string, string>)).catch(() => setMasterBalance(null)),
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
      const res = await saveAllRules({
        feishu,
        global_rules: globalRules,
        fund_rules: fundRules,
        expected_global_version: typeof globalRules.version === 'number' ? globalRules.version : undefined,
        expected_fund_version: typeof fundRules.version === 'number' ? fundRules.version : undefined,
      })
      // 回写版本号,避免下次保存误报 409
      setGlobalRules((p) => ({ ...p, version: res.global_version }))
      setFundRules((p) => ({ ...p, version: res.fund_version }))
      addToast('保存成功', 'success')
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      addToast(extractError(err, status === 409 ? '配置已被他人修改,请刷新后重试' : '保存失败'), 'error')
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

  // ⑩ 失焦不再直接落库,改为暂存到 fundEdits,统一「保存改动」批量确认后才写
  const stageFundEdit = useCallback((accountId: number, field: string, value: string) => {
    const key = `${accountId}-${field}`
    setFundEdits((prev) => {
      const account = accounts.find((a) => a.id === accountId)
      const original = String(account?.[field as keyof SubAccount] ?? '')
      const next = { ...prev }
      if (String(value ?? '') === original) delete next[key]   // 改回原值=不算改动
      else next[key] = value
      return next
    })
  }, [accounts])

  const discardFundEdits = useCallback(() => setFundEdits({}), [])

  const commitFundEdits = useCallback(async () => {
    const keys = Object.keys(fundEdits)
    if (keys.length === 0) { addToast('无改动', 'info'); return }
    if (!confirm(`确认保存 ${keys.length} 项子账户资金参数改动?这些直接影响实盘借币/风控。`)) return
    // 按账户分组,一次 patch 多字段
    const byAccount: Record<number, Record<string, string | null>> = {}
    for (const k of keys) {
      const sep = k.indexOf('-')
      const id = Number(k.slice(0, sep))
      const field = k.slice(sep + 1)
      ;(byAccount[id] ??= {})[field] = fundEdits[k] || null
    }
    setCommittingFund(true)
    try {
      for (const [idStr, patch] of Object.entries(byAccount)) {
        const id = Number(idStr)
        // E1: 单笔挂单变更时,保底额自动 ≥ 30%
        if (patch.single_order_amount) {
          const orderAmt = parseFloat(patch.single_order_amount)
          if (!isNaN(orderAmt) && orderAmt > 0) {
            const minRequired = Math.ceil(orderAmt * 0.3)
            const account = accounts.find((a) => a.id === id)
            const currentMin = parseFloat((patch.min_balance ?? account?.min_balance ?? '0') || '0') || 0
            if (currentMin < minRequired) patch.min_balance = String(minRequired)
          }
        }
        await patchSubAccountFundParams(id, patch)
        setAccounts((prev) => prev.map((a) => a.id === id ? { ...a, ...patch } as SubAccount : a))
      }
      addToast(`已保存 ${keys.length} 项`, 'success')
      setFundEdits({})
    } catch (err: unknown) {
      addToast(extractError(err, '保存失败'), 'error')
    }
    setCommittingFund(false)
  }, [fundEdits, accounts, addToast])

  // 可转口径 = 主账户余额(自动划转对应主账户操作),不再用子账户合计
  const mbNum = (k: string) => (masterBalance ? Math.round(parseFloat(masterBalance[k]) || 0) : null)

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
      {/* Title bar — 嵌入模态时隐藏(模态栏已展示标题/关闭),避免重复 */}
      {!embedded && (
        <div className="flex items-center justify-between px-4 py-2 bg-[#0d0d14] border-b border-border shrink-0">
          <span className="text-sm font-semibold">规则设置</span>
          <button
            onClick={closeRules}
            className="text-muted-foreground hover:text-foreground text-lg leading-none px-1"
          >
            ✕
          </button>
        </div>
      )}

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
              <InlineField label="合约爆仓率提醒 <" value={fv('margin_rate_alert')} onChange={(v) => updateF('margin_rate_alert', v)} suffix="%" width="w-10" title="合约距爆仓安全垫(=(保证金余额−维持保证金)÷保证金余额×100)低于此 % 即告警;hedge_via_master 看主账户合约。0=禁用。已接入引擎生效" />
              <InlineField label="杠杆风险率提醒 <" value={fv('leverage_risk_alert')} onChange={(v) => updateF('leverage_risk_alert', v)} width="w-12" />
              <InlineField label="保证金告警冷却" value={fv('risk_alert_cooldown_sec')} onChange={(v) => updateF('risk_alert_cooldown_sec', v)} suffix="秒" width="w-14" title="同一子账户「保证金水平」告警的专属冷却:低保证金会每30秒持续命中,此冷却内只发一次,防刷屏。默认1800(30分钟),0=退回全局节流" />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <TogglePill label="划转失败提醒" active={!!feishu.enable_transfer_fail_alert} onChange={(v) => updateFBool('enable_transfer_fail_alert', v)} />
              <TogglePill label="新增借币提醒" active={!!feishu.enable_new_borrow_alert} onChange={(v) => updateFBool('enable_new_borrow_alert', v)} />
              <TogglePill label="借币成功提醒" active={feishu.enable_borrow_success_alert !== false} onChange={(v) => updateFBool('enable_borrow_success_alert', v)} />
              <TogglePill label="还币成功提醒" active={feishu.enable_repay_success_alert !== false} onChange={(v) => updateFBool('enable_repay_success_alert', v)} />
            </div>
            {/* 显示偏好(仅切换表格展示口径,不改变任何交易行为)—— 与上方功能开关分区 */}
            <div className="flex items-center gap-2 flex-wrap pt-1.5 border-t border-border/40">
              <span className="text-muted-foreground/60 text-[10px]">显示</span>
              <TogglePill label="最大可借金额(U/数量)" active={maxBorrowToggle} onChange={(v) => {
                setMaxBorrowToggle(v)
                try { localStorage.setItem('hc_borrow_display_mode', v ? 'usdt' : 'qty') } catch { /* ignore */ }
              }} />
              <span className="text-muted-foreground/50 text-[9px]">仅切换「金额限制」列展示口径,不影响行为</span>
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
              <span className="text-positive/80 text-[10px]">主账户</span>
              <span className="text-muted-foreground">全仓可转: <span className="text-foreground font-mono tabular-nums">{mbNum('margin_usdt_free') ?? '-'}</span></span>
              <span className="text-muted-foreground">合约可转: <span className="text-foreground font-mono tabular-nums">{mbNum('futures_available') ?? '-'}</span></span>
              <span className="text-muted-foreground">现货可转: <span className="text-foreground font-mono tabular-nums">{mbNum('spot_usdt_free') ?? '-'}</span></span>
              <span className="text-muted-foreground/50 text-[9px]">(主账户余额;自动划转对应主账户)</span>
            </div>
            <div className="flex items-center gap-2 text-[11px] pt-1 border-t border-border/30">
              <InlineField label="主账户保留下限" value={frv('base_margin_amount')} onChange={(v) => updateFR('base_margin_amount', v)} suffix="U" width="w-14" title="自动补子账户保证金时,主账户(现货+合约可用+全仓)USDT 总额须保留此值、不被动用,护住对冲保证金不被抽干;每次补入额=min(请求额, 主账户总可用−此值)。0=不保留" />
              <span className="text-muted-foreground/50 text-[9px]">自动平衡补子账户时,主账户保底此额,护对冲保证金不被抽干</span>
            </div>
          </div>

          {/* -- Sub-Account Table -- */}
          {Object.keys(fundEdits).length > 0 && (
            <div className="flex items-center gap-2 text-[11px] bg-amber-400/10 border border-amber-400/30 rounded px-2 py-1">
              <span className="text-amber-400">未保存 {Object.keys(fundEdits).length} 项资金参数改动(失焦仅暂存,需确认才落库)</span>
              <button onClick={commitFundEdits} disabled={committingFund} className="ml-auto px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/80 disabled:opacity-40">{committingFund ? '保存中...' : '保存改动'}</button>
              <button onClick={discardFundEdits} className="px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-accent">放弃</button>
            </div>
          )}
          <div className="bg-[#111118] rounded border border-border overflow-x-auto">
            <table className="w-full text-[11px] border-collapse [&_th]:px-1 [&_td]:px-1">
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
                  <th className="px-1.5 py-1.5 text-right font-medium" title="风控预警阈值:保证金水平低于此值即软暂停该子账户下单;有值则覆盖全局「风险值阈值」。已接入引擎生效">风控阈</th>
                  <th className="px-1.5 py-1.5 text-right font-medium" title="风险值低于风控阈时,每周期从主账户(按划转顺序)补入该金额 USDT 到子账户保证金,直到风险值恢复;留空=该子账户不自动平衡。需 hedge_via_master + 主账户有余额。已接入引擎生效">单笔划</th>
                  <th className="px-1.5 py-1.5 text-right font-medium" title="子账户保证金保底 USDT:低于此从主账户补足;无持仓且富余时把多余划回主账户(保底留此额)。已接入引擎生效">保底额</th>
                  <th className="px-1.5 py-1.5 text-right font-medium" title="该子账户单笔下单额(USDT):有值则覆盖全局「单笔金额」;优先级 单币种规则 > 子账户 > 全局。已接入引擎生效">挂单单笔</th>
                  <th className="px-1.5 py-1.5 text-right font-medium" title="每账户借币金额上限(USDT,=maxBorrowable 封顶)，留空跟随全局;此列已接入引擎生效">金额限制</th>
                  <th className="px-1.5 py-1.5 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => {
                  const bal = balances[a.id]
                  const fcv = (field: string): string | null => {
                    const key = `${a.id}-${field}`
                    return key in fundEdits ? fundEdits[key] : ((a[field as keyof SubAccount] ?? null) as string | null)
                  }
                  const fcd = (field: string) => `${a.id}-${field}` in fundEdits
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
                      <EditableCell accountId={a.id} field="risk_threshold" value={fcv('risk_threshold')} dirty={fcd('risk_threshold')} editingCells={editingCells} setEditingCells={setEditingCells} onSave={stageFundEdit} />
                      <EditableCell accountId={a.id} field="single_transfer_amount" value={fcv('single_transfer_amount')} dirty={fcd('single_transfer_amount')} editingCells={editingCells} setEditingCells={setEditingCells} onSave={stageFundEdit} />
                      <EditableCell accountId={a.id} field="min_balance" value={fcv('min_balance')} dirty={fcd('min_balance')} editingCells={editingCells} setEditingCells={setEditingCells} onSave={stageFundEdit} />
                      <EditableCell accountId={a.id} field="single_order_amount" value={fcv('single_order_amount')} dirty={fcd('single_order_amount')} editingCells={editingCells} setEditingCells={setEditingCells} onSave={stageFundEdit} />
                      <EditableCell accountId={a.id} field="max_borrow_amount" value={fcv('max_borrow_amount')} dirty={fcd('max_borrow_amount')} editingCells={editingCells} setEditingCells={setEditingCells} onSave={stageFundEdit} />
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
          <p className="text-[9px] text-muted-foreground/50 px-1">
            全列已接入引擎:风控阈(风险下限,触发自动补保证金/下单暂停)、单笔划(每次从主账户补入额)、保底额(子账户保证金保底)、挂单单笔(覆盖全局下单额)、金额限制(借币封顶)。主→子自动平衡需 hedge_via_master + 主账户 USDT 充足;留空「单笔划」=该子账户不自动平衡(仅手动划转)。
          </p>
        </div>

        {/* ====== RIGHT COLUMN ====== */}
        <div className="flex-1 space-y-3 min-w-0">
          {/* -- BNB Management -- */}
          <div className="bg-[#111118] rounded border border-border p-3 space-y-2.5">
            {/* BNB 抵扣手续费开关(每用户,作用于本用户各子账户) */}
            <div className="flex items-center gap-2 flex-wrap text-[11px] pb-1.5 border-b border-border/40">
              <span className="text-muted-foreground">BNB 抵扣手续费</span>
              <button
                onClick={() => setGlobalRules((p) => ({ ...p, bnb_burn_enabled: !(p.bnb_burn_enabled === true || p.bnb_burn_enabled === 'true') }))}
                className={`px-2 py-0.5 rounded text-[11px] ${(globalRules.bnb_burn_enabled === true || globalRules.bnb_burn_enabled === 'true') ? 'bg-positive/20 text-positive' : 'bg-accent text-muted-foreground'}`}
              >
                {(globalRules.bnb_burn_enabled === true || globalRules.bnb_burn_enabled === 'true') ? '已开启(下单+杠杆利息)' : '已关闭'}
              </button>
              <span className="text-muted-foreground/60 text-[10px]">引擎对本用户各子账户统一下发 spotBNBBurn/interestBNBBurn;保存后于下个 BNB 检查周期生效</span>
            </div>
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
              <span className="text-muted-foreground" title="残留负债清理:每此间隔清掉子账户「无持仓的小额(<50U)非USDT币种欠款」(持币足额直接还/缺口小额买回补还)。已接入引擎生效">全仓负债转换间隔</span>
              <InlineField
                value={debtIntervalHr}
                onChange={(v) => updateFR('debt_convert_interval_sec', String((parseFloat(v) || 0) * 3600))}
                suffix="小时"
                width="w-8"
                title="残留负债清理间隔:清子账户无持仓的小额币种残留欠款。已接入引擎生效"
              />
            </div>
          </div>

          {/* -- Trading Parameters -- */}
          <div className="bg-[#111118] rounded border border-border p-3 space-y-2.5">
            <div className="flex items-center gap-6 flex-wrap text-[11px]">
              <InlineField label="自动推送点差" value={gv('auto_push_spread')} onChange={(v) => updateG('auto_push_spread', v)} width="w-10" />
              <InlineField label="日利息拦截" value={gv('interest_filter')} onChange={(v) => updateG('interest_filter', v)} suffix="%" width="w-10" />
            </div>
            <div className="flex items-center gap-3 flex-wrap text-[11px]" title="自动推送二次确认:点差达标的币先等此秒数复核点差仍≥推送阈值才推(防瞬时跳点误推);点差≥下方值则直推不等。已接入引擎生效">
              <InlineField label="推送二次确认" value={gv('confirm_delay_sec')} onChange={(v) => updateG('confirm_delay_sec', v)} suffix="秒" width="w-8" title="自动推送前的二次确认等待秒数;0=不二次确认直推。已接入引擎生效" />
              <span className="text-muted-foreground">点差≥</span>
              <InlineField value={gv('confirm_skip_spread')} onChange={(v) => updateG('confirm_skip_spread', v)} width="w-8" title="点差≥此值直接推送,跳过二次确认等待。已接入引擎生效" />
              <span className="text-muted-foreground">直接推送(不二次确认)</span>
            </div>
            <div className="flex items-center gap-6 flex-wrap text-[11px]">
              <InlineField label="点差不足移除" value={gv('remove_spread')} onChange={(v) => updateG('remove_spread', v)} width="w-10" />
              <InlineField label="单仓最大亏损" value={gv('max_loss_per_position')} onChange={(v) => updateG('max_loss_per_position', v)} suffix="U" width="w-10" title="单仓盯市浮亏达此 USDT 即强制平仓(合约平+现货买回,余下按还币规则);留空或 0=禁用。已接入引擎生效" />
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
