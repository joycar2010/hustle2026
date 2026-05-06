import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { manualTransfer, getAccountBalance } from '@/api/engine'
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
  const [accountId, setAccountId] = useState(defaultAccountId || accounts[0]?.id || 0)
  const [fromWallet, setFromWallet] = useState('futures')
  const [toWallet, setToWallet] = useState('margin')
  const [amount, setAmount] = useState('')
  const [asset, setAsset] = useState('USDT')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [balance, setBalance] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!accountId) return
    getAccountBalance(accountId)
      .then(setBalance)
      .catch(() => {})
  }, [accountId])

  const handleSubmit = async () => {
    if (!amount || parseFloat(amount) <= 0) {
      setError('请输入有效金额')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const result = await manualTransfer(accountId, {
        from_wallet: fromWallet,
        to_wallet: toWallet,
        asset,
        amount: parseFloat(amount),
      })
      setSuccess(result.message || '划转成功')
      setAmount('')
      getAccountBalance(accountId).then(setBalance).catch(() => {})
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || '划转失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card className="w-[calc(100vw-2rem)] max-w-[420px] max-h-[90vh] overflow-y-auto">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">手动划转</CardTitle>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="text-[10px] text-muted-foreground mb-1 block">账户</label>
            <select
              value={accountId}
              onChange={(e) => setAccountId(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.note} (#{a.id})</option>
              ))}
            </select>
          </div>

          {balance.margin_level && (
            <div className="grid grid-cols-3 gap-2 rounded-md border border-border/50 p-2 text-[10px]">
              <div>
                <span className="text-muted-foreground">杠杆可用</span>
                <p className="font-mono">{formatNumber(balance.margin_usdt_free)}</p>
              </div>
              <div>
                <span className="text-muted-foreground">合约余额</span>
                <p className="font-mono">{formatNumber(balance.futures_total_balance)}</p>
              </div>
              <div>
                <span className="text-muted-foreground">保证金水平</span>
                <p className="font-mono">{formatNumber(balance.margin_level)}</p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-muted-foreground mb-1 block">源钱包</label>
              <select
                value={fromWallet}
                onChange={(e) => setFromWallet(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
              >
                {WALLET_TYPES.map((w) => (
                  <option key={w.value} value={w.value}>{w.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground mb-1 block">目标钱包</label>
              <select
                value={toWallet}
                onChange={(e) => setToWallet(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs"
              >
                {WALLET_TYPES.map((w) => (
                  <option key={w.value} value={w.value}>{w.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-muted-foreground mb-1 block">资产</label>
              <Input value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} className="text-xs" />
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground mb-1 block">金额</label>
              <Input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
                className="text-xs"
              />
            </div>
          </div>

          {error && <p className="text-xs text-negative">{error}</p>}
          {success && <p className="text-xs text-positive">{success}</p>}

          <Button
            onClick={handleSubmit}
            disabled={loading || fromWallet === toWallet}
            className="w-full text-xs"
          >
            {loading ? '划转中...' : `划转 ${asset}`}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
