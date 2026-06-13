import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import { manualTransfer, crossAccountTransfer, getAccountBalance } from '@/api/engine'
import { formatNumber } from '@/lib/utils'

interface SubAccount {
  id: number
  note: string
}

interface TransferDialogProps {
  accounts: SubAccount[]
  defaultAccountId?: number
  onClose: () => void
}

const WALLET_TYPES = [
  { value: 'margin', label: '杠杆账户' },
  { value: 'spot', label: '现货账户' },
  { value: 'futures', label: '合约账户' },
]

export function TransferDialog({ accounts, defaultAccountId, onClose }: TransferDialogProps) {
  const [mode, setMode] = useState<'internal' | 'cross'>('internal')
  const [accountId, setAccountId] = useState(defaultAccountId || accounts[0]?.id || 0)
  const [fromWallet, setFromWallet] = useState('futures')
  const [toWallet, setToWallet] = useState('margin')
  const [amount, setAmount] = useState('')
  const [asset, setAsset] = useState('USDT')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [balance, setBalance] = useState<Record<string, string>>({})
  // cross-account state
  const [crossDir, setCrossDir] = useState<'out' | 'in'>('out')
  const [cpType, setCpType] = useState<'master' | 'sub'>('master')
  const [cpSubId, setCpSubId] = useState(0)
  const [crossFrom, setCrossFrom] = useState('spot')
  const [crossTo, setCrossTo] = useState('spot')

  useEffect(() => {
    if (!accountId) return
    getAccountBalance(accountId)
      .then(setBalance)
      .catch(() => {})
  }, [accountId])

  const reset = () => { setError(''); setSuccess('') }

  const handleInternal = async () => {
    if (!amount || parseFloat(amount) <= 0) { setError('请输入有效金额'); return }
    setLoading(true); reset()
    try {
      const result = await manualTransfer(accountId, {
        from_wallet: fromWallet, to_wallet: toWallet, asset, amount: parseFloat(amount),
      })
      setSuccess(result.message || '划转成功')
      setAmount('')
      getAccountBalance(accountId).then(setBalance).catch(() => {})
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || '划转失败')
    } finally { setLoading(false) }
  }

  const handleCross = async () => {
    if (!amount || parseFloat(amount) <= 0) { setError('请输入有效金额'); return }
    if (cpType === 'sub' && !cpSubId) { setError('请选择对手子账户'); return }
    setLoading(true); reset()
    try {
      const result = await crossAccountTransfer(accountId, {
        direction: crossDir,
        counterparty_type: cpType,
        counterparty_sub_account_id: cpType === 'sub' ? cpSubId : undefined,
        from_wallet: crossFrom,
        to_wallet: crossTo,
        asset, amount: parseFloat(amount),
      })
      setSuccess(result.message || '划转成功')
      setAmount('')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || '划转失败')
    } finally { setLoading(false) }
  }

  const otherAccounts = accounts.filter((a) => a.id !== accountId)
  const anchorNote = accounts.find((a) => a.id === accountId)?.note || `#${accountId}`
  const cpLabel = cpType === 'master' ? '主账户' : (otherAccounts.find((a) => a.id === cpSubId)?.note || '对手子账户')
  const [srcL, dstL] = crossDir === 'out' ? [anchorNote, cpLabel] : [cpLabel, anchorNote]

  const tabCls = (active: boolean) =>
    `text-sm font-semibold pb-0.5 transition-colors ${active ? 'text-foreground border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'}`
  const selCls = 'w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card className="w-[calc(100vw-2rem)] max-w-[440px] max-h-[90vh] overflow-y-auto">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button onClick={() => { setMode('internal'); reset() }} className={tabCls(mode === 'internal')}>内部划转</button>
              <button onClick={() => { setMode('cross'); reset() }} className={tabCls(mode === 'cross')}>跨账户划转</button>
            </div>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="text-[10px] text-muted-foreground mb-1 block">{mode === 'cross' ? '本账户' : '账户'}</label>
            <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))} className={selCls}>
              {accounts.map((a) => (<option key={a.id} value={a.id}>{a.note} (#{a.id})</option>))}
            </select>
          </div>

          {balance.margin_level && (
            <div className="grid grid-cols-3 gap-2 rounded-md border border-border/50 p-2 text-[10px]">
              <div><span className="text-muted-foreground">杠杆可用</span><p className="font-mono">{formatNumber(balance.margin_usdt_free)}</p></div>
              <div><span className="text-muted-foreground">合约余额</span><p className="font-mono">{formatNumber(balance.futures_total_balance)}</p></div>
              <div><span className="text-muted-foreground">现货可用</span><p className="font-mono">{formatNumber(balance.spot_usdt_free)}</p></div>
            </div>
          )}

          {mode === 'internal' ? (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-muted-foreground mb-1 block">源钱包</label>
                <select value={fromWallet} onChange={(e) => setFromWallet(e.target.value)} className={selCls}>
                  {WALLET_TYPES.map((w) => (<option key={w.value} value={w.value}>{w.label}</option>))}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground mb-1 block">目标钱包</label>
                <select value={toWallet} onChange={(e) => setToWallet(e.target.value)} className={selCls}>
                  {WALLET_TYPES.map((w) => (<option key={w.value} value={w.value}>{w.label}</option>))}
                </select>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-muted-foreground mb-1 block">方向</label>
                  <select value={crossDir} onChange={(e) => setCrossDir(e.target.value as 'out' | 'in')} className={selCls}>
                    <option value="out">本账户转出</option>
                    <option value="in">本账户转入</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground mb-1 block">对手账户</label>
                  <select value={cpType} onChange={(e) => setCpType(e.target.value as 'master' | 'sub')} className={selCls}>
                    <option value="master">主账户</option>
                    <option value="sub">其他子账户</option>
                  </select>
                </div>
              </div>
              {cpType === 'sub' && (
                <select value={cpSubId} onChange={(e) => setCpSubId(Number(e.target.value))} className={selCls}>
                  <option value={0}>选择对手子账户</option>
                  {otherAccounts.map((a) => (<option key={a.id} value={a.id}>{a.note} (#{a.id})</option>))}
                </select>
              )}
              <div className="flex items-center justify-center gap-2 text-[12px] py-0.5">
                <span className="px-2 py-1 rounded border border-primary/30 bg-primary/10 text-primary">{srcL}</span>
                <span className="text-primary">→</span>
                <span className="px-2 py-1 rounded border border-positive/30 bg-positive/10 text-positive">{dstL}</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-muted-foreground mb-1 block">源钱包</label>
                  <select value={crossFrom} onChange={(e) => setCrossFrom(e.target.value)} className={selCls}>
                    {WALLET_TYPES.map((w) => (<option key={w.value} value={w.value}>{w.label}</option>))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground mb-1 block">目标钱包</label>
                  <select value={crossTo} onChange={(e) => setCrossTo(e.target.value)} className={selCls}>
                    {WALLET_TYPES.map((w) => (<option key={w.value} value={w.value}>{w.label}</option>))}
                  </select>
                </div>
              </div>
            </>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-muted-foreground mb-1 block">资产</label>
              <Input value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} className="text-xs" />
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground mb-1 block">金额</label>
              <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" className="text-xs" />
            </div>
          </div>

          {error && <p className="text-xs text-negative">{error}</p>}
          {success && <p className="text-xs text-positive">{success}</p>}

          {mode === 'cross' && (
            <p className="text-[10px] text-muted-foreground/60">经主账户万向划转(需主账户开启「万向划转」权限);主↔子、子↔子均可。</p>
          )}

          <Button
            onClick={mode === 'internal' ? handleInternal : handleCross}
            disabled={loading || (mode === 'internal' && fromWallet === toWallet)}
            className="w-full text-xs"
          >
            {loading ? '划转中...' : `划转 ${asset}`}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
