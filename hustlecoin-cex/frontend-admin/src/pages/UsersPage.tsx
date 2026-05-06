import { useEffect, useState, useCallback } from 'react'
import {
  listUsers, createUser, updateUser, deleteUser, resetPassword,
  getUserSubAccounts, createSubAccount, updateSubAccount, deleteSubAccount, syncSubAccountPermissions,
  getMasterAccount, createMasterAccount, updateMasterAccount, deleteMasterAccount,
  listEngineUsers, startUserEngine, stopUserEngine,
  listProxies, bindProxy,
  feishuLookupByPhone,
  listRoles, getUserRoles, assignUserRole, revokeUserRole,
  type UserItem, type SubAccountItem, type MasterAccountItem, type EngineUserStatus, type ProxyItem,
  type RoleItem,
} from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { formatNumber } from '@/lib/utils'
import {
  Plus, RotateCcw, Users, Link, Activity,
  Play, Square, RefreshCw, Shield, Pencil, Trash2, Key,
} from 'lucide-react'

type Tab = 'accounts' | 'bindings' | 'engine'

export function UsersPage() {
  const [tab, setTab] = useState<Tab>('accounts')

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">用户管理</h1>
      </div>

      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <TabButton active={tab === 'accounts'} onClick={() => setTab('accounts')} icon={Users} label="用户账号" />
        <TabButton active={tab === 'bindings'} onClick={() => setTab('bindings')} icon={Link} label="绑定账户" />
        <TabButton active={tab === 'engine'} onClick={() => setTab('engine')} icon={Activity} label="引擎控制" />
      </div>

      {tab === 'accounts' && <AccountsTab />}
      {tab === 'bindings' && <BindingsTab />}
      {tab === 'engine' && <EngineTab />}
    </div>
  )
}

function TabButton({ active, onClick, icon: Icon, label }: {
  active: boolean; onClick: () => void; icon: React.ComponentType<{ className?: string }>; label: string
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
        active ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  )
}

// ─── Tab 1: User Accounts ───

function AccountsTab() {
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [editTarget, setEditTarget] = useState<UserItem | null>(null)
  const [resetTarget, setResetTarget] = useState<UserItem | null>(null)
  const [roleTarget, setRoleTarget] = useState<UserItem | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    listUsers().then(setUsers).finally(() => setLoading(false))
  }, [])

  useEffect(reload, [reload])

  const totalUsers = users.length
  const activeUsers = users.filter(u => u.is_active).length
  const disabledUsers = users.filter(u => !u.is_active).length
  const adminUsers = users.filter(u => u.role === 'SUPER_ADMIN' || u.role === 'ADMIN').length

  const handleDelete = async (u: UserItem) => {
    if (!confirm(`确认删除用户 ${u.username}？此操作将禁用该用户。`)) return
    try {
      await deleteUser(u.id)
      addToast('用户已禁用', 'success')
      reload()
    } catch (err: unknown) { addToast(extractError(err, '操作失败'), 'error') }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MiniCard label="总用户" value={totalUsers} />
        <MiniCard label="已启用" value={activeUsers} color="text-positive" />
        <MiniCard label="已禁用" value={disabledUsers} color="text-negative" />
        <MiniCard label="管理员" value={adminUsers} color="text-primary" />
      </div>

      <div className="flex justify-end">
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" /> 创建用户
        </Button>
      </div>

      {showCreate && (
        <UserFormDialog
          onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); reload(); addToast('用户创建成功', 'success') }}
        />
      )}

      {editTarget && (
        <UserFormDialog
          user={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => { setEditTarget(null); reload(); addToast('用户更新成功', 'success') }}
        />
      )}

      {resetTarget && (
        <ResetPasswordDialog
          user={resetTarget}
          onClose={() => setResetTarget(null)}
          onDone={() => { setResetTarget(null); addToast('密码已重置', 'success') }}
        />
      )}

      {roleTarget && (
        <UserRoleDialog
          user={roleTarget}
          onClose={() => setRoleTarget(null)}
          onDone={() => { setRoleTarget(null); addToast('角色分配成功', 'success') }}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">用户名</th>
                <th className="px-4 py-3">邮箱</th>
                <th className="px-4 py-3">角色</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">飞书</th>
                <th className="px-4 py-3">最后登录</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : users.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">暂无用户</td></tr>
              ) : (
                users.map((u) => (
                  <tr key={u.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3">{u.id}</td>
                    <td className="px-4 py-3 font-medium">{u.username}</td>
                    <td className="px-4 py-3 text-muted-foreground">{u.email || '-'}</td>
                    <td className="px-4 py-3">
                      <Badge variant={u.role === 'SUPER_ADMIN' ? 'default' : u.role === 'ADMIN' ? 'warning' : 'secondary'}>
                        {u.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={u.is_active ? 'success' : 'destructive'}>
                        {u.is_active ? '活跃' : '禁用'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {u.feishu_open_id ? (
                        <Badge variant="outline" className="text-[10px]">已绑定</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString('zh-CN') : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" title="编辑" onClick={() => setEditTarget(u)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" title="重置密码" onClick={() => setResetTarget(u)}>
                          <RotateCcw className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" title="分配角色" onClick={() => setRoleTarget(u)}>
                          <Shield className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" title="删除" onClick={() => handleDelete(u)}>
                          <Trash2 className="h-3.5 w-3.5 text-negative" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Tab 2: Bound Accounts ───

function BindingsTab() {
  const [users, setUsers] = useState<UserItem[]>([])
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  const [subAccounts, setSubAccounts] = useState<SubAccountItem[]>([])
  const [masterAccount, setMasterAccount] = useState<MasterAccountItem | null>(null)
  const [proxies, setProxies] = useState<ProxyItem[]>([])
  const [loading, setLoading] = useState(false)
  const [showCreateSub, setShowCreateSub] = useState(false)
  const [showMasterForm, setShowMasterForm] = useState(false)
  const [editingSub, setEditingSub] = useState<SubAccountItem | null>(null)
  const [bindingTarget, setBindingTarget] = useState<SubAccountItem | null>(null)
  const [syncing, setSyncing] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    listUsers().then(setUsers)
    listProxies().then(setProxies)
  }, [])

  const loadData = useCallback((userId: number) => {
    setLoading(true)
    Promise.all([
      getUserSubAccounts(userId),
      getMasterAccount(userId),
    ]).then(([subs, ma]) => {
      setSubAccounts(subs)
      setMasterAccount(ma)
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (selectedUserId) loadData(selectedUserId)
  }, [selectedUserId, loadData])

  useEffect(() => {
    if (users.length > 0 && !selectedUserId) setSelectedUserId(users[0].id)
  }, [users, selectedUserId])

  const handleSyncPermissions = async () => {
    if (!selectedUserId) return
    setSyncing(true)
    try {
      const result = await syncSubAccountPermissions(selectedUserId)
      if (result.failed > 0) {
        addToast(`同步完成: ${result.synced} 成功, ${result.failed} 失败`, 'info')
      } else {
        addToast(`权限同步成功 (${result.synced} 个账户)`, 'success')
      }
      loadData(selectedUserId)
    } catch (err: unknown) { addToast(extractError(err, '权限同步失败'), 'error') }
    finally { setSyncing(false) }
  }

  const handleDeleteSub = async (sa: SubAccountItem) => {
    if (!selectedUserId || !confirm(`确认删除子账户 ${sa.note}？`)) return
    try {
      await deleteSubAccount(selectedUserId, sa.id)
      addToast('子账户已删除', 'success')
      loadData(selectedUserId)
    } catch (err: unknown) { addToast(extractError(err, '删除失败（可能存在持仓）'), 'error') }
  }

  const handleDeleteMaster = async () => {
    if (!selectedUserId || !confirm('确认删除主账户？')) return
    try {
      await deleteMasterAccount(selectedUserId)
      addToast('主账户已删除', 'success')
      loadData(selectedUserId)
    } catch (err: unknown) { addToast(extractError(err, '删除失败'), 'error') }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select
          className="flex h-9 rounded-md border border-input px-3 py-1 text-sm"
          value={selectedUserId ?? ''}
          onChange={(e) => setSelectedUserId(Number(e.target.value))}
        >
          <option value="" disabled>选择用户</option>
          {users.map(u => (
            <option key={u.id} value={u.id}>{u.username} ({u.role})</option>
          ))}
        </select>
        <Button size="sm" variant="outline" onClick={() => selectedUserId && loadData(selectedUserId)}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
        {selectedUserId && (
          <>
            <Button size="sm" onClick={() => setShowCreateSub(true)}>
              <Plus className="h-4 w-4" /> 新增子账户
            </Button>
            {!masterAccount && (
              <Button size="sm" variant="outline" onClick={() => setShowMasterForm(true)}>
                <Key className="h-4 w-4" /> 绑定主账户
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={handleSyncPermissions} disabled={syncing}>
              <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? '同步中...' : '同步权限'}
            </Button>
          </>
        )}
      </div>

      {showCreateSub && selectedUserId && (
        <CreateSubAccountDialog
          userId={selectedUserId}
          onClose={() => setShowCreateSub(false)}
          onCreated={() => { setShowCreateSub(false); loadData(selectedUserId); addToast('子账户创建成功', 'success') }}
        />
      )}

      {showMasterForm && selectedUserId && (
        <MasterAccountDialog
          userId={selectedUserId}
          existing={masterAccount}
          onClose={() => setShowMasterForm(false)}
          onSaved={() => { setShowMasterForm(false); loadData(selectedUserId); addToast('主账户保存成功', 'success') }}
        />
      )}

      {editingSub && selectedUserId && (
        <EditSubAccountDialog
          userId={selectedUserId}
          subAccount={editingSub}
          onClose={() => setEditingSub(null)}
          onSaved={() => { setEditingSub(null); loadData(selectedUserId); addToast('子账户更新成功', 'success') }}
        />
      )}

      {bindingTarget && selectedUserId && (
        <ProxyBindDialog
          subAccount={bindingTarget}
          proxies={proxies}
          onClose={() => setBindingTarget(null)}
          onBound={() => { setBindingTarget(null); loadData(selectedUserId); addToast('代理绑定成功', 'success') }}
        />
      )}

      {loading ? (
        <div className="text-center text-muted-foreground py-8">加载中...</div>
      ) : (
        <div className="space-y-4">
          {/* Master Account */}
          {masterAccount && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2"><Key className="h-4 w-4 text-primary" /> 主账户</span>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setShowMasterForm(true)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={handleDeleteMaster}>
                      <Trash2 className="h-3.5 w-3.5 text-negative" />
                    </Button>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                  <div><span className="text-muted-foreground">API Key: </span><span className="font-mono">{masterAccount.api_key_masked}</span></div>
                  <div><span className="text-muted-foreground">验证: </span>
                    <Badge variant={masterAccount.is_verified ? 'success' : 'secondary'}>{masterAccount.is_verified ? '已验证' : '未验证'}</Badge>
                  </div>
                  <div><span className="text-muted-foreground">创建时间: </span><span className="text-xs">{masterAccount.created_at?.slice(0, 19)}</span></div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Sub Accounts */}
          {subAccounts.length === 0 && !masterAccount ? (
            <div className="text-center text-muted-foreground py-8">
              {selectedUserId ? '该用户暂无绑定账户' : '请选择用户'}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {subAccounts.map(sa => (
                <Card key={sa.id}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{sa.note}</span>
                          <Badge variant={sa.is_enabled ? 'success' : 'destructive'}>
                            {sa.is_enabled ? '启用' : '禁用'}
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">ID: {sa.id} | {sa.email}</p>
                      </div>
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" title="编辑" onClick={() => setEditingSub(sa)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setBindingTarget(sa)}>
                          <Shield className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" title="删除" onClick={() => handleDeleteSub(sa)}>
                          <Trash2 className="h-3.5 w-3.5 text-negative" />
                        </Button>
                      </div>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">API Key</span>
                        <span className="font-mono">{sa.api_key_masked}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">持仓数</span>
                        <span>{sa.positions_count}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">现货</span>
                        <Badge variant={sa.spot_enabled ? 'success' : 'secondary'} className="text-[10px]">
                          {sa.spot_enabled ? 'ON' : 'OFF'}
                        </Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">杠杆</span>
                        <Badge variant={sa.margin_enabled ? 'success' : 'secondary'} className="text-[10px]">
                          {sa.margin_enabled ? 'ON' : 'OFF'}
                        </Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">合约</span>
                        <Badge variant={sa.futures_enabled ? 'success' : 'secondary'} className="text-[10px]">
                          {sa.futures_enabled ? 'ON' : 'OFF'}
                        </Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">连接方式</span>
                        {sa.proxy ? (
                          <span className="text-blue-400">
                            代理: {sa.proxy.region || sa.proxy.name || sa.proxy.host}
                            {sa.proxy.days_left != null && <span className="text-muted-foreground ml-1">({sa.proxy.days_left}天)</span>}
                          </span>
                        ) : (
                          <span className="text-cyan-400">直连</span>
                        )}
                      </div>
                      <div className="col-span-2 flex justify-between">
                        <span className="text-muted-foreground">权限同步</span>
                        <span className="text-muted-foreground">
                          {sa.last_validated_at ? new Date(sa.last_validated_at).toLocaleString('zh-CN') : '未同步'}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Tab 3: Engine Control ───

function EngineTab() {
  const [engines, setEngines] = useState<EngineUserStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    listEngineUsers().then(setEngines).finally(() => setLoading(false))
  }, [])

  useEffect(reload, [reload])

  const handleStart = async (userId: number) => {
    setActionLoading(userId)
    try {
      await startUserEngine(userId)
      addToast('启动信号已发送', 'success')
      setTimeout(reload, 2000)
    } catch (err: unknown) { addToast(extractError(err, '启动失败'), 'error') }
    finally { setActionLoading(null) }
  }

  const handleStop = async (userId: number) => {
    setActionLoading(userId)
    try {
      await stopUserEngine(userId)
      addToast('停止信号已发送', 'success')
      setTimeout(reload, 2000)
    } catch (err: unknown) { addToast(extractError(err, '停止失败'), 'error') }
    finally { setActionLoading(null) }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={reload}>
          <RefreshCw className="h-3.5 w-3.5" /> 刷新
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[750px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">用户</th>
                <th className="px-4 py-3">引擎状态</th>
                <th className="px-4 py-3 text-right">Worker 数</th>
                <th className="px-4 py-3 text-right">持仓数</th>
                <th className="px-4 py-3 text-right">累计 PnL</th>
                <th className="px-4 py-3">最近交易</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : engines.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">暂无引擎数据</td></tr>
              ) : (
                engines.map(e => {
                  const pnl = parseFloat(e.total_pnl)
                  return (
                    <tr key={e.user_id} className="border-b last:border-0 hover:bg-accent/50">
                      <td className="px-4 py-3 font-medium">{e.username}</td>
                      <td className="px-4 py-3">
                        <Badge variant={e.status === 'RUNNING' ? 'success' : 'secondary'}>
                          {e.status === 'RUNNING' ? '运行中' : '已停止'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right">{e.worker_count}</td>
                      <td className="px-4 py-3 text-right">{e.open_positions}</td>
                      <td className={`px-4 py-3 text-right ${pnl >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {formatNumber(e.total_pnl)}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {e.last_trade_at ? new Date(e.last_trade_at).toLocaleString('zh-CN') : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1">
                          {e.status === 'RUNNING' ? (
                            <Button size="sm" variant="ghost" disabled={actionLoading === e.user_id} onClick={() => handleStop(e.user_id)}>
                              <Square className="h-3.5 w-3.5" /> 停止
                            </Button>
                          ) : (
                            <Button size="sm" variant="ghost" disabled={actionLoading === e.user_id} onClick={() => handleStart(e.user_id)}>
                              <Play className="h-3.5 w-3.5" /> 启动
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Dialogs ───

function MiniCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Card>
      <CardContent className="p-3">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-xl font-bold ${color || ''}`}>{value}</p>
      </CardContent>
    </Card>
  )
}

function UserFormDialog({ user, onClose, onSaved }: { user?: UserItem; onClose: () => void; onSaved: () => void }) {
  const isEdit = !!user
  const [form, setForm] = useState({
    username: user?.username || '',
    password: '',
    email: user?.email || '',
    role: user?.role || 'USER',
    max_sub_accounts: user?.max_sub_accounts || 5,
    feishu_open_id: user?.feishu_open_id || '',
    feishu_phone: user?.feishu_phone || '',
    feishu_union_id: user?.feishu_union_id || '',
  })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [lookingUp, setLookingUp] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const handleFeishuLookup = async () => {
    const phone = form.feishu_phone.trim()
    if (!phone) { addToast('请先输入飞书手机号', 'error'); return }
    setLookingUp(true)
    try {
      const result = await feishuLookupByPhone(phone)
      setForm((f) => ({
        ...f,
        feishu_open_id: result.open_id || f.feishu_open_id,
        feishu_union_id: result.union_id || f.feishu_union_id,
      }))
      addToast('飞书ID获取成功', 'success')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '查询失败'
      addToast(msg, 'error')
    } finally { setLookingUp(false) }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!isEdit) {
      if (!form.username.trim()) { setError('请填写用户名'); return }
      if (!form.password) { setError('请填写密码'); return }
      if (form.password.length < 6) { setError('密码至少 6 位'); return }
    }
    setSaving(true)
    try {
      if (isEdit) {
        await updateUser(user!.id, {
          email: form.email || undefined,
          role: form.role,
          max_sub_accounts: form.max_sub_accounts,
          feishu_open_id: form.feishu_open_id || undefined,
          feishu_phone: form.feishu_phone || undefined,
          feishu_union_id: form.feishu_union_id || undefined,
        })
      } else {
        await createUser({
          username: form.username,
          password: form.password,
          email: form.email || undefined,
          role: form.role,
          max_sub_accounts: form.max_sub_accounts,
          feishu_open_id: form.feishu_open_id || undefined,
          feishu_phone: form.feishu_phone || undefined,
          feishu_union_id: form.feishu_union_id || undefined,
        })
      }
      onSaved()
    } catch (err: unknown) {
      setError(extractError(err, isEdit ? '更新失败' : '创建失败'))
    } finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{isEdit ? '编辑用户' : '创建用户'}</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">用户名</label>
            <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required disabled={isEdit} />
          </div>
          {!isEdit && (
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">密码</label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required autoComplete="new-password" />
            </div>
          )}
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">邮箱</label>
            <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">角色</label>
            <select className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="USER">USER</option>
              <option value="ADMIN">ADMIN</option>
              <option value="SUPER_ADMIN">SUPER_ADMIN</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">子账户上限</label>
            <Input type="number" value={form.max_sub_accounts} onChange={(e) => setForm({ ...form, max_sub_accounts: parseInt(e.target.value) || 5 })} />
          </div>

          {/* Feishu Section */}
          <div className="col-span-2 border-t pt-3 mt-1">
            <p className="text-xs text-muted-foreground mb-2">飞书通知配置</p>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">飞书 Open ID</label>
            <Input value={form.feishu_open_id} onChange={(e) => setForm({ ...form, feishu_open_id: e.target.value })} placeholder="ou_xxxxxxxxx" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">飞书手机号</label>
            <div className="flex gap-1.5">
              <Input className="flex-1" value={form.feishu_phone} onChange={(e) => setForm({ ...form, feishu_phone: e.target.value })} placeholder="+86..." />
              <Button type="button" size="sm" variant="outline" disabled={lookingUp || !form.feishu_phone.trim()} onClick={handleFeishuLookup}>
                {lookingUp ? '查询中...' : '获取飞书ID'}
              </Button>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">飞书 Union ID</label>
            <Input value={form.feishu_union_id} onChange={(e) => setForm({ ...form, feishu_union_id: e.target.value })} placeholder="on_xxxxxxxxx" />
          </div>

          {error && <p className="col-span-2 text-sm text-negative">{error}</p>}
          <div className="col-span-2 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>{saving ? '保存中...' : isEdit ? '更新' : '创建'}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function CreateSubAccountDialog({ userId, onClose, onCreated }: { userId: number; onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({ note: '', email: '', api_key: '', api_secret: '' })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.note.trim()) { setError('请填写备注名'); return }
    if (!form.email.trim()) { setError('请填写邮箱'); return }
    if (!form.api_key.trim()) { setError('请填写 API Key'); return }
    if (!form.api_secret.trim()) { setError('请填写 API Secret'); return }
    setSaving(true)
    try {
      await createSubAccount(userId, form)
      onCreated()
    } catch (err: unknown) {
      setError(extractError(err, '创建失败'))
    } finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">新增子账户</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">备注名</label>
            <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} required />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">邮箱</label>
            <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
          </div>
          <div className="space-y-1 col-span-2">
            <label className="text-xs text-muted-foreground">API Key</label>
            <Input value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} required name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          <div className="space-y-1 col-span-2">
            <label className="text-xs text-muted-foreground">API Secret</label>
            <Input type="password" value={form.api_secret} onChange={(e) => setForm({ ...form, api_secret: e.target.value })} required name="binance-secret" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          {error && <p className="col-span-2 text-sm text-negative">{error}</p>}
          <div className="col-span-2 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>{saving ? '创建中...' : '创建'}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function EditSubAccountDialog({ userId, subAccount, onClose, onSaved }: {
  userId: number; subAccount: SubAccountItem; onClose: () => void; onSaved: () => void
}) {
  const [form, setForm] = useState({
    note: subAccount.note,
    email: subAccount.email,
    is_enabled: subAccount.is_enabled,
    api_key: '',
    api_secret: '',
  })
  const [saving, setSaving] = useState(false)

  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      const body: Record<string, unknown> = { note: form.note, email: form.email, is_enabled: form.is_enabled }
      if (form.api_key) body.api_key = form.api_key
      if (form.api_secret) body.api_secret = form.api_secret
      await updateSubAccount(userId, subAccount.id, body)
      onSaved()
    } catch (err: unknown) {
      setError(extractError(err, '更新失败'))
    } finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">编辑子账户: {subAccount.note}</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">备注名</label>
            <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">邮箱</label>
            <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div className="space-y-1 col-span-2">
            <label className="text-xs text-muted-foreground">API Key (留空不修改)</label>
            <Input value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder="留空保持不变" name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          <div className="space-y-1 col-span-2">
            <label className="text-xs text-muted-foreground">API Secret (留空不修改)</label>
            <Input type="password" value={form.api_secret} onChange={(e) => setForm({ ...form, api_secret: e.target.value })} placeholder="留空保持不变" name="binance-secret" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          {error && <p className="col-span-2 text-sm text-negative">{error}</p>}
          <div className="col-span-2 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function MasterAccountDialog({ userId, existing, onClose, onSaved }: {
  userId: number; existing: MasterAccountItem | null; onClose: () => void; onSaved: () => void
}) {
  const [form, setForm] = useState({ api_key: '', api_secret: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.api_key.trim()) { setError('请填写 API Key'); return }
    if (!form.api_secret.trim()) { setError('请填写 API Secret'); return }
    setSaving(true)
    try {
      if (existing) {
        await updateMasterAccount(userId, form)
      } else {
        await createMasterAccount(userId, form)
      }
      onSaved()
    } catch (err: unknown) {
      setError(extractError(err, existing ? '更新失败' : '绑定失败'))
    } finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{existing ? '更新主账户' : '绑定主账户'}</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">API Key</label>
            <Input value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} required name="binance-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">API Secret</label>
            <Input type="password" value={form.api_secret} onChange={(e) => setForm({ ...form, api_secret: e.target.value })} required name="binance-secret" autoComplete="new-password" data-1p-ignore data-lpignore="true" />
          </div>
          {error && <p className="text-sm text-negative">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function ResetPasswordDialog({ user, onClose, onDone }: { user: UserItem; onClose: () => void; onDone: () => void }) {
  const [newPwd, setNewPwd] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleReset = async () => {
    setError('')
    if (!newPwd) { setError('请输入新密码'); return }
    if (newPwd.length < 6) { setError('密码至少 6 位'); return }
    setSaving(true)
    try { await resetPassword(user.id, newPwd); onDone() }
    catch (err: unknown) { setError(extractError(err, '重置失败')) }
    finally { setSaving(false) }
  }

  return (
    <Card>
      <CardContent className="p-4">
        <p className="mb-3 text-sm">重置 <strong>{user.username}</strong> 的密码</p>
        <div className="flex gap-2">
          <Input type="password" placeholder="新密码（至少6位）" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} autoComplete="new-password" />
          <Button onClick={handleReset} disabled={saving}>{saving ? '...' : '重置'}</Button>
          <Button variant="ghost" onClick={onClose}>取消</Button>
        </div>
        {error && <p className="mt-2 text-sm text-negative">{error}</p>}
      </CardContent>
    </Card>
  )
}

function ProxyBindDialog({ subAccount, proxies, onClose, onBound }: {
  subAccount: SubAccountItem; proxies: ProxyItem[]; onClose: () => void; onBound: () => void
}) {
  const [selectedProxyId, setSelectedProxyId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  const handleBind = async () => {
    if (!selectedProxyId) return
    setSaving(true)
    try { await bindProxy({ sub_account_id: subAccount.id, proxy_id: selectedProxyId }); onBound() }
    finally { setSaving(false) }
  }

  const activeProxies = proxies.filter(p => p.status === 'active')

  return (
    <Card>
      <CardContent className="p-4">
        <p className="mb-3 text-sm">为 <strong>{subAccount.note}</strong> 绑定代理</p>
        <div className="flex gap-2">
          <select
            className="flex h-9 flex-1 rounded-md border border-input px-3 py-1 text-sm"
            value={selectedProxyId ?? ''}
            onChange={(e) => setSelectedProxyId(Number(e.target.value))}
          >
            <option value="" disabled>选择代理</option>
            {activeProxies.map(p => (
              <option key={p.id} value={p.id}>{p.name || p.host}:{p.port} ({p.region || p.provider})</option>
            ))}
          </select>
          <Button onClick={handleBind} disabled={saving || !selectedProxyId}>{saving ? '...' : '绑定'}</Button>
          <Button variant="ghost" onClick={onClose}>取消</Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── User Role Assignment Dialog ───

function UserRoleDialog({ user, onClose, onDone }: { user: UserItem; onClose: () => void; onDone: () => void }) {
  const [allRoles, setAllRoles] = useState<RoleItem[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [originalIds, setOriginalIds] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    Promise.all([listRoles(), getUserRoles(user.id)])
      .then(([roles, ids]) => {
        setAllRoles(roles.filter(r => r.is_active))
        const s = new Set(ids)
        setSelectedIds(new Set(s))
        setOriginalIds(s)
      })
      .finally(() => setLoading(false))
  }, [user.id])

  const toggle = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const toRemove = [...originalIds].filter(id => !selectedIds.has(id))
      const toAdd = [...selectedIds].filter(id => !originalIds.has(id))
      for (const id of toRemove) await revokeUserRole(user.id, id)
      for (const id of toAdd) await assignUserRole(user.id, id)
      onDone()
    } catch (e: unknown) {
      addToast(e instanceof Error ? e.message : '分配失败', 'error')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <Card className="w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <CardHeader>
          <CardTitle className="text-sm">分配角色 — {user.username}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {loading ? (
            <div className="text-muted-foreground py-4 text-center text-sm">加载中...</div>
          ) : allRoles.length === 0 ? (
            <div className="text-muted-foreground py-4 text-center text-sm">暂无角色，请先到系统管理初始化权限</div>
          ) : (
            allRoles.map(r => (
              <label key={r.id} className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-accent/50 cursor-pointer text-sm">
                <input type="checkbox" checked={selectedIds.has(r.id)} onChange={() => toggle(r.id)} />
                <span className="font-medium">{r.role_name}</span>
                <span className="text-xs text-muted-foreground">({r.role_code})</span>
              </label>
            ))
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={onClose}>取消</Button>
            <Button size="sm" onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
