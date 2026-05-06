import { useEffect, useState, useCallback } from 'react'
import {
  getSubAccounts, toggleSubAccount, validateSubAccount,
  getMasterAccount, updateMasterAccount, validateMasterAccount,
  createSubAccount, getIpWhitelist, updateSubAccountKeys,
  deleteSubAccount, updateSubAccount, getApiPermissions,
  checkPermissions, getMasterPermissions,
} from '@/api/accounts'
import { getAccountBalance } from '@/api/engine'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { extractError } from '@/api/client'
import { cn, formatNumber } from '@/lib/utils'
import { Power, Shield, RefreshCw, Wallet, Plus, Eye, EyeOff, X, Key, ChevronDown, ChevronUp, Trash2, AlertTriangle } from 'lucide-react'
import { IpWhitelistPanel } from '@/components/accounts/IpWhitelistPanel'

const SUB_PERM_FIELDS = [
  { key: 'enableSpotAndMarginTrading', label: '现货及杠杆交易' },
  { key: 'enableMargin', label: '杠杆质押借币还款和划转' },
  { key: 'enableFutures', label: '合约' },
  { key: 'permitsUniversalTransfer', label: '万向划转' },
  { key: 'enableVanillaOptions', label: '欧式期权' },
]

const MASTER_PERM_FIELDS = [
  { key: 'enableSpotAndMarginTrading', label: '现货及杠杆交易' },
  { key: 'enableMargin', label: '杠杆质押借币还款和划转' },
  { key: 'enableFutures', label: '合约' },
  { key: 'enableInternalTransfer', label: '子母账户划转' },
  { key: 'permitsUniversalTransfer', label: '万向划转' },
  { key: 'enableVanillaOptions', label: '欧式期权' },
]

function PermBadges({ perms, fields }: { perms: Record<string, boolean>; fields: { key: string; label: string }[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {fields.map(({ key, label }) => (
        <Badge key={key} className={cn(
          'text-[10px]',
          perms[key]
            ? 'bg-positive/20 text-positive border-positive/30'
            : 'bg-negative/20 text-negative border-negative/30',
        )}>
          {perms[key] ? '✓' : '✗'} {label}
        </Badge>
      ))}
    </div>
  )
}

interface SubAccount {
  id: number
  note: string
  email: string
  is_enabled: boolean
  api_key: string
  api_secret_masked: string
  margin_enabled: boolean
  futures_enabled: boolean
  spot_enabled: boolean
  bnb_burn_enabled: boolean
  bnb_interest_enabled: boolean
  order_amount?: string
  single_order_amount?: string
  min_balance?: string
  single_transfer_amount?: string
  risk_threshold?: string
  max_positions?: number
  max_borrow_amount?: string
  last_validated_at?: string
  created_at: string
  updated_at: string
  proxy?: { host: string; region: string | null; name: string | null; end_date?: string | null; days_left?: number | null } | null
}

interface BalanceInfo {
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
}

interface IpInfo {
  ipRestrict: boolean
  ipList: Array<{ ip: string }>
}

interface MasterAccountData {
  id: number
  api_key: string
  api_secret_masked: string
  is_verified: boolean
  created_at: string
}

export function AccountsPage() {
  const [accounts, setAccounts] = useState<SubAccount[]>([])
  const [balances, setBalances] = useState<Record<number, BalanceInfo>>({})
  const [ipInfos, setIpInfos] = useState<Record<number, IpInfo>>({})
  const [masterAccount, setMasterAccount] = useState<MasterAccountData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshingAll, setRefreshingAll] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  // IP whitelist panel
  const [ipPanelAccountId, setIpPanelAccountId] = useState<number | null>(null)
  const [ipPanelAccountNote, setIpPanelAccountNote] = useState('')

  // Detail drawer
  const [detailAccount, setDetailAccount] = useState<SubAccount | null>(null)

  // Create dialog
  const [showCreate, setShowCreate] = useState(false)

  // Master account editing
  const [editingMaster, setEditingMaster] = useState(false)
  const [masterExpanded, setMasterExpanded] = useState(false)
  const [masterPerms, setMasterPerms] = useState<Record<string, boolean> | null>(null)
  const [masterPermLoading, setMasterPermLoading] = useState(false)
  const [masterIpRestrict, setMasterIpRestrict] = useState<boolean | null>(null)
  const [masterPermError, setMasterPermError] = useState<string | null>(null)
  const [masterKey, setMasterKey] = useState('')
  const [masterSecret, setMasterSecret] = useState('')
  const [masterSaving, setMasterSaving] = useState(false)

  const fetchAccounts = useCallback(async () => {
    try {
      const data = await getSubAccounts()
      setAccounts(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAccounts()
    getMasterAccount().then(setMasterAccount).catch(() => {})
  }, [fetchAccounts])

  // Fetch master permissions when expanded
  useEffect(() => {
    if (!masterExpanded || !masterAccount || masterPerms) return
    setMasterPermLoading(true)
    getMasterPermissions()
      .then((data: Record<string, unknown>) => {
        setMasterPerms({
          enableSpotAndMarginTrading: !!data.enableSpotAndMarginTrading,
          enableMargin: !!data.enableMargin,
          enableFutures: !!data.enableFutures,
          enableInternalTransfer: !!data.enableInternalTransfer,
          permitsUniversalTransfer: !!data.permitsUniversalTransfer,
          enableVanillaOptions: !!data.enableVanillaOptions,
        })
        setMasterIpRestrict(!!data.ipRestrict)
      })
      .catch((e: unknown) => {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'API Key 无效或已过期'
        setMasterPermError(detail)
      })
      .finally(() => setMasterPermLoading(false))
  }, [masterExpanded, masterAccount])

  // Fetch IP info for all accounts on load
  useEffect(() => {
    if (accounts.length === 0) return
    accounts.forEach((a) => {
      getIpWhitelist(a.id)
        .then((data: IpInfo) => setIpInfos((prev) => ({ ...prev, [a.id]: data })))
        .catch(() => {})
    })
  }, [accounts])

  const handleToggle = async (id: number) => {
    try {
      await toggleSubAccount(id)
      addToast('状态已切换', 'success')
      fetchAccounts()
    } catch {
      addToast('切换失败', 'error')
    }
  }

  const handleValidate = async (id: number) => {
    try {
      const result = await validateSubAccount(id)
      if (result.is_valid) {
        addToast('验证通过', 'success')
      } else {
        addToast(`验证失败: ${result.error}`, 'error')
      }
      fetchAccounts()
    } catch {
      addToast('验证失败', 'error')
    }
  }

  const handleFetchBalance = async (id: number) => {
    try {
      const data = await getAccountBalance(id)
      setBalances((prev) => ({ ...prev, [id]: data }))
    } catch {
      addToast('获取余额失败', 'error')
    }
  }

  const handleRefreshAll = async () => {
    setRefreshingAll(true)
    try {
      await Promise.allSettled(accounts.map((a) => handleFetchBalance(a.id)))
    } finally {
      setRefreshingAll(false)
    }
  }

  const handleSaveMaster = async () => {
    if (!masterKey.trim() || !masterSecret.trim()) return
    setMasterSaving(true)
    try {
      const data = await updateMasterAccount({ api_key: masterKey, api_secret: masterSecret })
      setMasterAccount(data)
      setEditingMaster(false)
      setMasterKey('')
      setMasterSecret('')
      addToast('主账户已更新', 'success')
    } catch (err: unknown) {
      addToast(extractError(err, '更新失败'), 'error')
    } finally {
      setMasterSaving(false)
    }
  }

  const getHealthColor = (accountId: number, riskThreshold?: string) => {
    const b = balances[accountId]
    if (!b) return 'bg-muted-foreground/20 text-muted-foreground'
    const level = parseFloat(b.margin_level)
    const threshold = parseFloat(riskThreshold || '1.5')
    if (isNaN(level) || level === 0) return 'bg-muted-foreground/20 text-muted-foreground'
    if (level >= 999) return 'bg-positive/20 text-positive'
    if (level > threshold * 1.5) return 'bg-positive/20 text-positive'
    if (level > threshold) return 'bg-yellow-500/20 text-yellow-400'
    return 'bg-negative/20 text-negative'
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">账户管理</h1>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={handleRefreshAll} disabled={refreshingAll || accounts.length === 0}>
            <RefreshCw size={14} className={cn(refreshingAll && 'animate-spin')} />
            <span className="ml-1 text-xs">{refreshingAll ? '刷新中...' : '刷新全部余额'}</span>
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus size={14} />
            <span className="ml-1 text-xs">新建账户</span>
          </Button>
        </div>
      </div>

      {/* Master Account */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">主账户</CardTitle>
            <button onClick={() => setMasterExpanded(!masterExpanded)} className="text-muted-foreground hover:text-foreground">
              {masterExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </CardHeader>
        <CardContent>
          {masterAccount ? (
            <div className="space-y-2">
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground">状态</span>
                <Badge className={cn(
                  masterAccount.is_verified
                    ? 'bg-positive/20 text-positive border-positive/30'
                    : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                )}>
                  {masterAccount.is_verified ? '已验证' : '未验证'}
                </Badge>
              </div>
              {masterExpanded && (
                <div className="space-y-2 text-xs border-t pt-2">
                  <div className="grid grid-cols-[80px_1fr] gap-1">
                    <span className="text-muted-foreground">API Key</span>
                    <span className="font-mono text-[11px]">{masterAccount.api_key.slice(0, 8)}...{masterAccount.api_key.slice(-4)}</span>
                    <span className="text-muted-foreground">Secret</span>
                    <span className="font-mono text-[11px]">{masterAccount.api_secret_masked}</span>
                    <span className="text-muted-foreground">创建时间</span>
                    <span>{new Date(masterAccount.created_at).toLocaleString('zh-CN')}</span>
                  </div>

                  {/* Master Permissions */}
                  <div className="space-y-1.5 border-t pt-2">
                    <p className="text-[10px] text-muted-foreground font-medium">交易权限</p>
                    {masterPermLoading ? (
                      <span className="text-[10px] text-muted-foreground">查询中...</span>
                    ) : masterPerms ? (
                      <PermBadges perms={masterPerms} fields={MASTER_PERM_FIELDS} />
                    ) : masterPermError ? (
                      <div className="flex items-center gap-1.5 text-[10px] text-negative bg-negative/10 rounded px-2 py-1">
                        <AlertTriangle size={12} />
                        <span>{masterPermError}</span>
                      </div>
                    ) : (
                      <span className="text-[10px] text-muted-foreground">权限查询失败</span>
                    )}
                  </div>

                  {/* Master IP Whitelist */}
                  <div className="space-y-1 border-t pt-2">
                    <p className="text-[10px] text-muted-foreground font-medium">IP 白名单自检</p>
                    {masterIpRestrict === null ? (
                      <span className="text-[10px] text-muted-foreground">{masterPermLoading ? '查询中...' : '未获取'}</span>
                    ) : (
                      <Badge className={cn(
                        'text-[10px]',
                        masterIpRestrict ? 'bg-positive/20 text-positive border-positive/30' : 'bg-negative/20 text-negative border-negative/30',
                      )}>
                        {masterIpRestrict ? '✓ IP 限制已启用' : '✗ IP 限制未启用'}
                      </Badge>
                    )}
                  </div>

                  {editingMaster ? (
                    <div className="space-y-2 border-t pt-2">
                      <Input value={masterKey} onChange={(e) => setMasterKey(e.target.value)} placeholder="新 API Key" className="text-xs" name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
                      <Input value={masterSecret} onChange={(e) => setMasterSecret(e.target.value)} placeholder="新 API Secret" type="password" className="text-xs" name="binance-secret" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={handleSaveMaster} disabled={masterSaving} className="text-xs">
                          {masterSaving ? '保存中...' : '保存'}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setEditingMaster(false)} className="text-xs">取消</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-2 border-t pt-2">
                      <Button size="sm" variant="outline" onClick={() => setEditingMaster(true)} className="text-xs">
                        <Key size={12} className="mr-1" />更新密钥
                      </Button>
                      <Button size="sm" variant="outline" onClick={async () => {
                        try {
                          await validateMasterAccount()
                          addToast('主账户验证通过', 'success')
                          getMasterAccount().then(setMasterAccount).catch(() => {})
                        } catch { addToast('验证失败', 'error') }
                      }} className="text-xs">
                        <RefreshCw size={12} className="mr-1" />验证
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-negative">
                <AlertTriangle size={14} />
                <span>主账户未配置 — IP 白名单功能需要主账户</span>
              </div>
              <div className="space-y-2">
                <Input value={masterKey} onChange={(e) => setMasterKey(e.target.value)} placeholder="API Key" className="text-xs" name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
                <Input value={masterSecret} onChange={(e) => setMasterSecret(e.target.value)} placeholder="API Secret" type="password" className="text-xs" name="binance-secret" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
                <Button size="sm" onClick={handleSaveMaster} disabled={masterSaving} className="text-xs">
                  {masterSaving ? '保存中...' : '配置主账户'}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sub Accounts */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">子账户 ({accounts.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">加载中...</p>
          ) : (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {accounts.map((a) => {
                const bal = balances[a.id]
                const ipInfo = ipInfos[a.id]
                return (
                  <div
                    key={a.id}
                    className="space-y-2.5 rounded-lg border bg-background p-4 cursor-pointer hover:border-primary/40 transition-colors"
                    onClick={() => setDetailAccount(a)}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{a.note || a.email}</span>
                      <Badge className={cn(
                        'text-[10px]',
                        a.is_enabled
                          ? 'bg-positive/20 text-positive border-positive/30'
                          : 'bg-negative/20 text-negative border-negative/30',
                      )}>
                        {a.is_enabled ? '启用' : '禁用'}
                      </Badge>
                    </div>

                    <div className="text-[11px] text-muted-foreground">{a.email}</div>

                    {/* Balance data */}
                    {bal ? (
                      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] border-t pt-2">
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">现货</span>
                          <span className="tabular-nums font-mono">{formatNumber(bal.spot_usdt_free)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">资金</span>
                          <span className="tabular-nums font-mono">{formatNumber(bal.funding_usdt)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">理财</span>
                          <span className="tabular-nums font-mono">{formatNumber(bal.earn_total)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">杠杆可用</span>
                          <span className="tabular-nums font-mono">{formatNumber(bal.margin_usdt_free)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">借入</span>
                          <span className={cn('tabular-nums font-mono', parseFloat(bal.margin_usdt_borrowed) > 0 && 'text-negative')}>{formatNumber(bal.margin_usdt_borrowed)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">风险值</span>
                          <span className={cn('tabular-nums font-mono', getHealthColor(a.id, a.risk_threshold).includes('negative') ? 'text-negative' : getHealthColor(a.id, a.risk_threshold).includes('yellow') ? 'text-yellow-400' : 'text-foreground')}>
                            {parseFloat(bal.margin_level) >= 999 ? '∞' : formatNumber(bal.margin_level)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">合约</span>
                          <span className="tabular-nums font-mono">{formatNumber(bal.futures_total_balance)}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="text-[10px] text-muted-foreground/50 border-t pt-2">点击余额按钮加载数据</div>
                    )}

                    {/* Status indicators */}
                    <div className="flex items-center gap-2 text-[10px] flex-wrap">
                      {ipInfo ? (
                        <span className={cn(
                          'px-1.5 py-0.5 rounded',
                          ipInfo.ipRestrict ? 'bg-positive/10 text-positive' : 'bg-negative/10 text-negative'
                        )}>
                          IP: {ipInfo.ipRestrict ? `已限制(${ipInfo.ipList?.length || 0})` : '⚠ 未限制'}
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground">IP: -</span>
                      )}
                      {a.proxy ? (
                        <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                          代理: {a.proxy.region || a.proxy.name || a.proxy.host}
                          {a.proxy.days_left != null && ` (${a.proxy.days_left}天)`}
                        </span>
                      ) : ipInfo?.ipRestrict ? (
                        <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400">直连</span>
                      ) : null}
                      {a.last_validated_at && (
                        <span className="text-muted-foreground">
                          验证: {new Date(a.last_validated_at).toLocaleDateString('zh-CN')}
                        </span>
                      )}
                      {a.max_positions && (
                        <span className="text-muted-foreground">坑位: {a.max_positions}</span>
                      )}
                    </div>

                    {/* Action buttons */}
                    <div className="flex gap-1 border-t pt-2" onClick={(e) => e.stopPropagation()}>
                      <Button size="sm" variant="ghost" onClick={() => handleToggle(a.id)} title={a.is_enabled ? '禁用' : '启用'}>
                        <Power size={14} className={a.is_enabled ? 'text-positive' : 'text-negative'} />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => handleValidate(a.id)} title="验证 API Key">
                        <RefreshCw size={14} />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => handleFetchBalance(a.id)} title="刷新余额">
                        <Wallet size={14} />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => { setIpPanelAccountId(a.id); setIpPanelAccountNote(a.note || a.email) }} title="IP 白名单">
                        <Shield size={14} />
                      </Button>
                    </div>
                  </div>
                )
              })}
              {accounts.length === 0 && (
                <p className="col-span-full py-8 text-center text-muted-foreground">暂无子账户</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* IP Whitelist Panel */}
      {ipPanelAccountId && (
        <IpWhitelistPanel
          accountId={ipPanelAccountId}
          accountNote={ipPanelAccountNote}
          onClose={() => {
            setIpPanelAccountId(null)
            // Refresh IP info for that account
            getIpWhitelist(ipPanelAccountId)
              .then((data: IpInfo) => setIpInfos((prev) => ({ ...prev, [ipPanelAccountId]: data })))
              .catch(() => {})
          }}
        />
      )}

      {/* Create Account Dialog */}
      {showCreate && (
        <CreateAccountDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); fetchAccounts() }}
        />
      )}

      {/* Account Detail Drawer */}
      {detailAccount && (
        <AccountDetailDrawer
          account={detailAccount}
          balance={balances[detailAccount.id]}
          ipInfo={ipInfos[detailAccount.id]}
          onClose={() => setDetailAccount(null)}
          onRefresh={() => { fetchAccounts(); handleFetchBalance(detailAccount.id) }}
          onOpenIpPanel={() => { setIpPanelAccountId(detailAccount.id); setIpPanelAccountNote(detailAccount.note || detailAccount.email); setDetailAccount(null) }}
        />
      )}
    </div>
  )
}


// ─── Create Account Dialog ────────────────────────────────────────

function CreateAccountDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({ note: '', email: '', api_key: '', api_secret: '' })
  const [showSecret, setShowSecret] = useState(false)
  const [saving, setSaving] = useState(false)
  const [perms, setPerms] = useState<Record<string, boolean> | null>(null)
  const [permChecking, setPermChecking] = useState(false)
  const [permError, setPermError] = useState('')
  const addToast = useToastStore((s) => s.addToast)

  const allPermsOk = perms ? SUB_PERM_FIELDS.every(({ key }) => perms[key]) : false

  const handleCheckPerms = async () => {
    if (!form.api_key || !form.api_secret) {
      addToast('请先填写 API Key 和 Secret', 'error')
      return
    }
    setPermChecking(true)
    setPermError('')
    setPerms(null)
    try {
      const data = await checkPermissions({ api_key: form.api_key, api_secret: form.api_secret })
      setPerms({
        enableSpotAndMarginTrading: !!data.enableSpotAndMarginTrading,
        enableMargin: !!data.enableMargin,
        enableFutures: !!data.enableFutures,
        enableInternalTransfer: !!data.enableInternalTransfer,
        permitsUniversalTransfer: !!data.permitsUniversalTransfer,
        enableVanillaOptions: !!data.enableVanillaOptions,
      })
    } catch (err: unknown) {
      setPermError(extractError(err, 'API Key 无效或网络错误'))
    } finally {
      setPermChecking(false)
    }
  }

  const handleSave = async () => {
    if (!form.note || !form.email || !form.api_key || !form.api_secret) {
      addToast('请填写所有必填项', 'error')
      return
    }
    if (!allPermsOk) {
      addToast('权限未全部开通，无法创建', 'error')
      return
    }
    setSaving(true)
    try {
      await createSubAccount(form)
      addToast('账户创建成功', 'success')
      onCreated()
    } catch (err: unknown) {
      addToast(extractError(err, '创建失败'), 'error')
    } finally {
      setSaving(false)
    }
  }

  const update = (key: string, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    if (key === 'api_key' || key === 'api_secret') {
      setPerms(null)
      setPermError('')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card className="w-[calc(100vw-2rem)] max-w-[480px] max-h-[85vh] overflow-y-auto">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">新建子账户</CardTitle>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <label className="text-[11px] text-muted-foreground">账户别名 *</label>
            <Input value={form.note} onChange={(e) => update('note', e.target.value)} placeholder="如: hustle-016" className="text-xs" />
          </div>
          <div className="space-y-2">
            <label className="text-[11px] text-muted-foreground">邮箱 *</label>
            <Input value={form.email} onChange={(e) => update('email', e.target.value)} placeholder="binance 子账户邮箱" className="text-xs" />
          </div>
          <div className="space-y-2">
            <label className="text-[11px] text-muted-foreground">API Key *</label>
            <Input value={form.api_key} onChange={(e) => update('api_key', e.target.value)} placeholder="API Key" className="text-xs font-mono" name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          <div className="space-y-2">
            <label className="text-[11px] text-muted-foreground">API Secret *</label>
            <div className="relative">
              <Input
                value={form.api_secret}
                onChange={(e) => update('api_secret', e.target.value)}
                placeholder="API Secret"
                type={showSecret ? 'text' : 'password'}
                className="text-xs font-mono pr-8"
                name="binance-secret"
                autoComplete="new-password"
                data-1p-ignore
                data-lpignore="true"
              />
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div className="space-y-2 border-t pt-3">
            <div className="flex items-center justify-between">
              <label className="text-[11px] text-muted-foreground">交易权限检查</label>
              <Button size="sm" variant="outline" onClick={handleCheckPerms} disabled={permChecking || !form.api_key || !form.api_secret} className="text-xs h-6 px-2">
                <RefreshCw size={11} className={cn('mr-1', permChecking && 'animate-spin')} />
                {permChecking ? '检查中...' : '验证权限'}
              </Button>
            </div>
            {perms ? (
              <>
                <PermBadges perms={perms} fields={SUB_PERM_FIELDS} />
                {!allPermsOk && (
                  <p className="text-[10px] text-negative">权限未全部开通，请在币安后台开启所有权限后重新验证</p>
                )}
              </>
            ) : permError ? (
              <p className="text-[10px] text-negative">{permError}</p>
            ) : (
              <p className="text-[10px] text-muted-foreground">填写 API Key/Secret 后点击「验证权限」</p>
            )}
          </div>

          <div className="flex gap-2 border-t pt-3">
            <Button onClick={handleSave} disabled={saving || !allPermsOk} className="flex-1 text-xs">
              {saving ? '创建中...' : allPermsOk ? '创建账户' : '权限未通过'}
            </Button>
            <Button variant="outline" onClick={onClose} className="text-xs">取消</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}


// ─── Account Detail Drawer ────────────────────────────────────────

interface AccountDetailDrawerProps {
  account: SubAccount
  balance?: BalanceInfo
  ipInfo?: IpInfo
  onClose: () => void
  onRefresh: () => void
  onOpenIpPanel: () => void
}

function AccountDetailDrawer({ account, balance, ipInfo: parentIpInfo, onClose, onRefresh, onOpenIpPanel }: AccountDetailDrawerProps) {
  const [editing, setEditing] = useState(false)
  const [editNote, setEditNote] = useState(account.note)
  const [editEmail, setEditEmail] = useState(account.email)
  const [showKeyUpdate, setShowKeyUpdate] = useState(false)
  const [newKey, setNewKey] = useState('')
  const [newSecret, setNewSecret] = useState('')
  const [showNewSecret, setShowNewSecret] = useState(false)
  const [keySaving, setKeySaving] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const [localIpInfo, setLocalIpInfo] = useState<IpInfo | null>(parentIpInfo || null)
  const [ipLoading, setIpLoading] = useState(!parentIpInfo)
  const [permissions, setPermissions] = useState<Record<string, boolean> | null>(null)
  const [permLoading, setPermLoading] = useState(true)
  const [localBalance, setLocalBalance] = useState<BalanceInfo | undefined>(balance)
  const [balLoading, setBalLoading] = useState(!balance)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    if (!balance) {
      getAccountBalance(account.id)
        .then((data: BalanceInfo) => { setLocalBalance(data); setBalLoading(false) })
        .catch(() => setBalLoading(false))
    }

    getIpWhitelist(account.id)
      .then((data: IpInfo) => { setLocalIpInfo(data); setIpLoading(false) })
      .catch(() => setIpLoading(false))

    getApiPermissions(account.id)
      .then((data: Record<string, unknown>) => {
        setPermissions({
          enableMargin: !!data.enableMargin,
          enableFutures: !!data.enableFutures,
          enableInternalTransfer: !!data.enableInternalTransfer,
          enableVanillaOptions: !!data.enableVanillaOptions,
          enableSpotAndMarginTrading: !!data.enableSpotAndMarginTrading,
          permitsUniversalTransfer: !!data.permitsUniversalTransfer,
        })
        setPermLoading(false)
      })
      .catch(() => setPermLoading(false))
  }, [account.id])

  const ipInfo = localIpInfo

  const handleSaveEdit = async () => {
    setEditSaving(true)
    try {
      await updateSubAccount(account.id, { note: editNote, email: editEmail })
      addToast('保存成功', 'success')
      setEditing(false)
      onRefresh()
    } catch (err: unknown) {
      addToast(extractError(err, '保存失败'), 'error')
    } finally {
      setEditSaving(false)
    }
  }

  const handleUpdateKeys = async () => {
    if (!newKey || !newSecret) {
      addToast('请填写 API Key 和 Secret', 'error')
      return
    }
    setKeySaving(true)
    try {
      await updateSubAccountKeys(account.id, { api_key: newKey, api_secret: newSecret })
      addToast('API Key 更新成功（已验证）', 'success')
      setShowKeyUpdate(false)
      setNewKey('')
      setNewSecret('')
      onRefresh()
    } catch (err: unknown) {
      addToast(extractError(err, 'Key 更新失败'), 'error')
    } finally {
      setKeySaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm(`确认删除账户 ${account.note}？此操作将禁用账户。`)) return
    try {
      await deleteSubAccount(account.id)
      addToast('账户已删除', 'success')
      onClose()
      onRefresh()
    } catch (err: unknown) {
      addToast(extractError(err, '删除失败'), 'error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50">
      <div
        className="w-full md:w-[480px] h-full bg-background border-l border-border overflow-y-auto"
      >
        <div className="sticky top-0 bg-background border-b border-border p-4 flex items-center justify-between z-10">
          <h2 className="text-sm font-semibold">账户详情 — {account.note}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
        </div>

        <div className="p-4 space-y-4">
          {/* Basic Info */}
          <section className="space-y-2">
            <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">基本信息</h3>
            <div className="grid grid-cols-[90px_1fr] gap-y-2 gap-x-3 text-xs">
              <span className="text-muted-foreground">别名</span>
              {editing ? (
                <Input value={editNote} onChange={(e) => setEditNote(e.target.value)} className="text-xs h-7" />
              ) : (
                <span>{account.note}</span>
              )}

              <span className="text-muted-foreground">邮箱</span>
              {editing ? (
                <Input value={editEmail} onChange={(e) => setEditEmail(e.target.value)} className="text-xs h-7" />
              ) : (
                <span>{account.email}</span>
              )}

              <span className="text-muted-foreground">状态</span>
              <Badge className={cn(
                'text-[10px] w-fit',
                account.is_enabled ? 'bg-positive/20 text-positive' : 'bg-negative/20 text-negative',
              )}>
                {account.is_enabled ? '启用' : '禁用'}
              </Badge>

              <span className="text-muted-foreground">API Key</span>
              <span className="font-mono text-[11px]">{account.api_key.slice(0, 8)}...{account.api_key.slice(-4)}</span>

              <span className="text-muted-foreground">Secret</span>
              <span className="font-mono text-[11px]">{account.api_secret_masked}</span>

              <span className="text-muted-foreground">上次验证</span>
              <span>{account.last_validated_at ? new Date(account.last_validated_at).toLocaleString('zh-CN') : '未验证'}</span>
            </div>
            {editing ? (
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSaveEdit} disabled={editSaving} className="text-xs">
                  {editSaving ? '保存中...' : '保存'}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(false)} className="text-xs">取消</Button>
              </div>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setEditing(true)} className="text-xs">编辑</Button>
            )}
          </section>

          {/* Trading Permissions (from Binance API) */}
          <section className="space-y-2 border-t pt-3">
            <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">交易权限</h3>
            {permLoading ? (
              <span className="text-[11px] text-muted-foreground">查询中...</span>
            ) : permissions ? (
              <PermBadges perms={permissions} fields={SUB_PERM_FIELDS} />
            ) : (
              <span className="text-[11px] text-muted-foreground">权限查询失败</span>
            )}
          </section>

          {/* Fund Parameters */}
          <section className="space-y-2 border-t pt-3">
            <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">资金参数</h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                { label: '挂单金额', value: account.single_order_amount },
                { label: '保底额', value: account.min_balance },
                { label: '单次划转', value: account.single_transfer_amount },
                { label: '风险阈值', value: account.risk_threshold },
                { label: '坑位上限', value: account.max_positions },
                { label: '借币限额', value: account.max_borrow_amount },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="tabular-nums">{value ?? '-'}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground">在「规则」页面管理资金参数</p>
          </section>

          {/* IP Whitelist */}
          <section className="space-y-2 border-t pt-3">
            <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">IP 白名单</h3>
            {ipLoading ? (
              <span className="text-[11px] text-muted-foreground">加载中...</span>
            ) : ipInfo ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Badge className={cn(
                    'text-[10px]',
                    ipInfo.ipRestrict ? 'bg-positive/20 text-positive' : 'bg-negative/20 text-negative',
                  )}>
                    {ipInfo.ipRestrict ? '已启用' : '未启用'}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">({ipInfo.ipList?.length || 0} 个 IP)</span>
                </div>
                {ipInfo.ipList?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {ipInfo.ipList.map((item) => (
                      <span key={item.ip} className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded">{item.ip}</span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <span className="text-[11px] text-muted-foreground">IP 白名单获取失败</span>
            )}
            <Button size="sm" variant="outline" onClick={onOpenIpPanel} className="text-xs">
              <Shield size={12} className="mr-1" />管理 IP 白名单
            </Button>
          </section>

          {/* Balance */}
          <section className="space-y-2 border-t pt-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">账户余额</h3>
              <Button size="sm" variant="ghost" className="h-5 px-1.5" onClick={async () => {
                setBalLoading(true)
                try {
                  const data = await getAccountBalance(account.id)
                  setLocalBalance(data)
                } catch { addToast('获取余额失败', 'error') }
                finally { setBalLoading(false) }
              }}>
                <RefreshCw size={11} className={cn(balLoading && 'animate-spin')} />
              </Button>
            </div>
            {balLoading ? (
              <span className="text-[11px] text-muted-foreground">加载中...</span>
            ) : localBalance ? (
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">现货可用</span><span className="tabular-nums font-mono">{formatNumber(localBalance.spot_usdt_free)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">现货冻结</span><span className="tabular-nums font-mono">{formatNumber(localBalance.spot_usdt_locked)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">资金账户</span><span className="tabular-nums font-mono">{formatNumber(localBalance.funding_usdt)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">理财账户</span><span className="tabular-nums font-mono">{formatNumber(localBalance.earn_total)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">风险值</span><span className="tabular-nums font-mono">{parseFloat(localBalance.margin_level) >= 999 ? '∞ (无借入)' : formatNumber(localBalance.margin_level)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">杠杆可用</span><span className="tabular-nums font-mono">{formatNumber(localBalance.margin_usdt_free)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">杠杆借入</span><span className={cn('tabular-nums font-mono', parseFloat(localBalance.margin_usdt_borrowed) > 0 && 'text-negative')}>{formatNumber(localBalance.margin_usdt_borrowed)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">合约余额</span><span className="tabular-nums font-mono">{formatNumber(localBalance.futures_total_balance)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">合约可用</span><span className="tabular-nums font-mono">{formatNumber(localBalance.futures_available)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">未实现盈亏</span><span className={cn('tabular-nums font-mono', parseFloat(localBalance.futures_unrealized_pnl) > 0 ? 'text-positive' : parseFloat(localBalance.futures_unrealized_pnl) < 0 ? 'text-negative' : '')}>{formatNumber(localBalance.futures_unrealized_pnl)}</span></div>
              </div>
            ) : (
              <span className="text-[11px] text-muted-foreground">获取失败</span>
            )}
          </section>

          {/* API Key Update */}
          <section className="space-y-2 border-t pt-3">
            <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">操作</h3>
            {showKeyUpdate ? (
              <div className="space-y-2 bg-muted/50 rounded p-3">
                <p className="text-[11px] text-muted-foreground">更换 API Key（自动验证）</p>
                <Input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="新 API Key" className="text-xs font-mono" name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
                <div className="relative">
                  <Input
                    value={newSecret}
                    onChange={(e) => setNewSecret(e.target.value)}
                    placeholder="新 API Secret"
                    type={showNewSecret ? 'text' : 'password'}
                    className="text-xs font-mono pr-8"
                    name="binance-secret"
                    autoComplete="new-password"
                    data-1p-ignore
                    data-lpignore="true"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewSecret(!showNewSecret)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showNewSecret ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleUpdateKeys} disabled={keySaving} className="text-xs">
                    {keySaving ? '更新中...' : '更新 Key'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setShowKeyUpdate(false)} className="text-xs">取消</Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setShowKeyUpdate(true)} className="text-xs">
                  <Key size={12} className="mr-1" />更换 API Key
                </Button>
                <Button size="sm" variant="outline" onClick={async () => {
                  try {
                    const result = await validateSubAccount(account.id)
                    addToast(result.is_valid ? '验证通过' : `验证失败: ${result.error}`, result.is_valid ? 'success' : 'error')
                    onRefresh()
                  } catch { addToast('验证失败', 'error') }
                }} className="text-xs">
                  <RefreshCw size={12} className="mr-1" />验证 Key
                </Button>
                <Button size="sm" variant="outline" className="text-xs text-negative hover:text-negative" onClick={handleDelete}>
                  <Trash2 size={12} className="mr-1" />删除账户
                </Button>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
