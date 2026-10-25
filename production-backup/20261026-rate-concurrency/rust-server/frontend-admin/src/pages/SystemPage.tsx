import { useEffect, useRef, useState } from 'react'
import {
  getSystemInfo, getGitHistory, gitPush, gitRollback, gitDelete, getServiceVersions,
  getDatabaseStats, getDatabaseTables, getTableData, backupDatabase, cleanupDatabase,
  listRoles, listPermissions, createRole, updateRole, deleteRole,
  getRolePermissions, assignPermission, revokePermission, seedRbac,
  getAicoinConfig, updateAicoinConfig, testAicoinConfig,
  listSSLCerts, uploadSSLCert, deleteSSLCert, deploySSLCert, scanLetsEncryptCerts,
  listProxies, createProxy, deleteProxy, healthCheckProxies,
  listProxyBindings, bindProxy, unbindProxy,
  getIpipgoOrders, syncIpipgoOrders,
  type SystemInfo, type GitCommit, type DatabaseStats, type TableInfo,
  type RoleItem, type PermissionItem, type SSLCert,
  type ProxyItem, type ProxyBinding, type IpipgoOrder,
  type ServiceVersion,
} from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import {
  GitBranch, Database, Shield, Upload, Trash2, Eye, Download,
  Plus, Lock, Pencil, Key, RefreshCw, X, Check,
  Zap, ShieldCheck, Globe, Rocket, ScanSearch, HeartPulse, Link2, Server,
  Radio, FileText, RotateCcw,
} from 'lucide-react'
import { WsMonitorPage } from '@/pages/WsMonitorPage'
import { AuditPage } from '@/pages/AuditPage'

type Tab = 'version' | 'database' | 'roles' | 'aicoin' | 'ssl' | 'proxies' | 'ws' | 'audit'

export function SystemPage() {
  const [tab, setTab] = useState<Tab>('version')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">系统管理</h1>

      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <TabBtn active={tab === 'version'} onClick={() => setTab('version')} icon={GitBranch} label="版本管理" />
        <TabBtn active={tab === 'database'} onClick={() => setTab('database')} icon={Database} label="数据库管理" />
        <TabBtn active={tab === 'roles'} onClick={() => setTab('roles')} icon={Shield} label="角色权限" />
        <TabBtn active={tab === 'aicoin'} onClick={() => setTab('aicoin')} icon={Zap} label="AiCoin配置" />
        <TabBtn active={tab === 'ssl'} onClick={() => setTab('ssl')} icon={ShieldCheck} label="SSL证书" />
        <TabBtn active={tab === 'proxies'} onClick={() => setTab('proxies')} icon={Globe} label="代理管理" />
        <TabBtn active={tab === 'ws'} onClick={() => setTab('ws')} icon={Radio} label="WS 监控" />
        <TabBtn active={tab === 'audit'} onClick={() => setTab('audit')} icon={FileText} label="审计日志" />
      </div>

      {tab === 'version' && <VersionTab />}
      {tab === 'database' && <DatabaseTab />}
      {tab === 'roles' && <RolesTab />}
      {tab === 'aicoin' && <AicoinTab />}
      {tab === 'ssl' && <SSLTab />}
      {tab === 'proxies' && <ProxiesMainTab />}
      {tab === 'ws' && <WsMonitorPage />}
      {tab === 'audit' && <AuditPage />}
    </div>
  )
}

function TabBtn({ active, onClick, icon: Icon, label }: {
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

// ─── Version Tab ───

function VersionTab() {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [services, setServices] = useState<ServiceVersion[]>([])
  const [commits, setCommits] = useState<GitCommit[]>([])
  const [loading, setLoading] = useState(true)
  const [pushMsg, setPushMsg] = useState('')
  const [pushing, setPushing] = useState(false)
  const [pushProgress, setPushProgress] = useState(0)   // 0=空闲, 1-100=进度条
  const pushTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    Promise.all([getSystemInfo(), getGitHistory(), getServiceVersions()])
      .then(([info, commits, versions]) => { setInfo(info); setCommits(commits); setServices(versions.services) })
      .finally(() => setLoading(false))
  }, [])

  const handlePush = async () => {
    if (!pushMsg.trim()) return
    setPushing(true)
    setPushProgress(3)
    if (pushTimer.current) clearInterval(pushTimer.current)
    // 后端 git push 为单次阻塞(无字节级进度),前端乐观分段推进至 92%,收到响应再填满
    pushTimer.current = setInterval(() => {
      setPushProgress((p) => (p >= 92 ? 92 : p + 2))
    }, 350)
    try {
      const res = await gitPush({ message: pushMsg })
      addToast(
        res.status === 'success'
          ? `推送成功${res.rust_synced === false ? '(Rust源未同步)' : ''}`
          : `推送失败: ${res.output?.slice(0, 120)}`,
        res.status === 'success' ? 'success' : 'error',
      )
      if (res.status === 'success') setPushMsg('')
      getGitHistory().then(setCommits)
      getServiceVersions().then(v => setServices(v.services))
    } catch {
      addToast('推送失败', 'error')
    } finally {
      if (pushTimer.current) { clearInterval(pushTimer.current); pushTimer.current = null }
      setPushProgress(100)
      setPushing(false)
      setTimeout(() => setPushProgress(0), 1500)
    }
  }

  const handleRollback = async (hash: string, shortHash: string) => {
    if (!confirm(`确认滚回到提交 ${shortHash}？这将丢弃之后的所有提交。`)) return
    setPushing(true)
    try {
      const res = await gitRollback({ commit_hash: hash })
      addToast(res.status === 'success' ? '滚回成功' : `滚回失败: ${res.output?.slice(0, 100)}`, res.status === 'success' ? 'success' : 'error')
      getGitHistory().then(setCommits)
      getServiceVersions().then(v => setServices(v.services))
    } finally { setPushing(false) }
  }

  const handleDelete = async (hash: string, shortHash: string) => {
    if (!confirm(`确认撤销提交 ${shortHash}？将创建一个反转提交。`)) return
    setPushing(true)
    try {
      const res = await gitDelete({ commit_hash: hash })
      addToast(res.status === 'success' ? '删除成功' : `删除失败: ${res.output?.slice(0, 100)}`, res.status === 'success' ? 'success' : 'error')
      getGitHistory().then(setCommits)
      getServiceVersions().then(v => setServices(v.services))
    } finally { setPushing(false) }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <div className="space-y-4">
      {/* Multi-Service Version Cards */}
      {services.length > 0 && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {services.map(s => (
            <Card key={s.service}>
              <CardContent className="p-4 space-y-1.5">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">{s.service}</p>
                  <Badge variant={s.status === 'running' || s.status === 'active' || s.status === 'deployed' ? 'default' : 'destructive'}>
                    {s.status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">{s.host}</p>
                {s.version && <p className="text-xs">版本: {s.version}</p>}
                <p className="text-xs font-mono">提交: {s.git_commit || '-'}</p>
                {s.uptime && <p className="text-xs">运行: {s.uptime}</p>}
                {s.last_deploy && <p className="text-xs">部署: {s.last_deploy}</p>}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* System Info */}
      {info && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 lg:grid-cols-3">
          <InfoCard label="后端版本" value={info.backend_version} />
          <InfoCard label="Python" value={info.python_version} />
          <InfoCard label="运行时长" value={info.uptime} />
          <InfoCard label="Git 分支" value={info.git_branch || '-'} />
          <InfoCard label="最新提交" value={info.git_commit || '-'} />
          <InfoCard label="数据库" value={info.db_version} />
        </div>
      )}

      {/* Git Push */}
      <Card>
        <CardHeader><CardTitle className="text-sm">GitHub 推送</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              placeholder="推送备注信息..."
              value={pushMsg}
              onChange={(e) => setPushMsg(e.target.value)}
              className="flex-1"
            />
            <Button onClick={handlePush} disabled={pushing || !pushMsg.trim()}>
              <Upload className="h-4 w-4" /> {pushing ? '推送中...' : '推送'}
            </Button>
          </div>
          {pushProgress > 0 && (
            <div className="mt-3 space-y-1">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {pushProgress >= 100 ? '完成 ✓'
                    : pushProgress >= 92 ? '推送到 GitHub coin…'
                    : pushProgress >= 70 ? '提交…'
                    : pushProgress >= 50 ? '暂存两端源码 + dist…'
                    : pushProgress >= 25 ? '拉取 Rust 服务器源码…'
                    : '准备备份…'}
                </span>
                <span className="tabular-nums">{pushProgress}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-all duration-300" style={{ width: `${pushProgress}%` }} />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Git History */}
      <Card>
        <CardHeader><CardTitle className="text-sm">提交历史</CardTitle></CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[600px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">Hash</th>
                <th className="px-4 py-3">消息</th>
                <th className="px-4 py-3">作者</th>
                <th className="px-4 py-3">时间</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {commits.map(c => (
                <tr key={c.hash} className="border-b last:border-0 hover:bg-accent/50">
                  <td className="px-4 py-2 font-mono text-xs">{c.short_hash}</td>
                  <td className="px-4 py-2 truncate max-w-xs">{c.message}</td>
                  <td className="px-4 py-2 text-muted-foreground">{c.author}</td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">{c.date?.slice(0, 19)}</td>
                  <td className="px-4 py-2">
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" disabled={pushing}
                        onClick={() => handleRollback(c.hash, c.short_hash)}
                        title="滚回到此提交">
                        <RotateCcw className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" disabled={pushing}
                        onClick={() => handleDelete(c.hash, c.short_hash)}
                        title="撤销此提交"
                        className="text-destructive hover:text-destructive">
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Database Tab ───

function DatabaseTab() {
  const [stats, setStats] = useState<DatabaseStats | null>(null)
  const [tables, setTables] = useState<TableInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [viewTable, setViewTable] = useState<string | null>(null)
  const [tableData, setTableData] = useState<{ columns: string[]; rows: Record<string, unknown>[] } | null>(null)
  const [tableLoading, setTableLoading] = useState(false)
  const [backupLoading, setBackupLoading] = useState(false)
  const [cleanupLoading, setCleanupLoading] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    Promise.all([getDatabaseStats(), getDatabaseTables()])
      .then(([s, t]) => { setStats(s); setTables(t) })
      .finally(() => setLoading(false))
  }, [])

  const handleViewTable = async (name: string) => {
    setViewTable(name)
    setTableLoading(true)
    try {
      const data = await getTableData(name)
      setTableData(data)
    } catch { addToast('加载失败', 'error') }
    finally { setTableLoading(false) }
  }

  const handleBackup = async () => {
    setBackupLoading(true)
    try {
      const res = await backupDatabase()
      addToast(res.status === 'success' ? `备份成功: ${res.size_mb}MB` : `备份失败`, res.status === 'success' ? 'success' : 'error')
    } finally { setBackupLoading(false) }
  }

  const handleCleanup = async () => {
    setCleanupLoading(true)
    try {
      const res = await cleanupDatabase()
      if (res.status === 'success') {
        const d = res.deleted
        addToast(`清理完成: 交易日志${d.trade_logs}条, 审计${d.audit_logs}条, 健康日志${d.proxy_health_logs}条`, 'success')
      }
    } finally { setCleanupLoading(false) }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <div className="space-y-4">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <InfoCard label="数据库大小" value={stats.size} />
          <InfoCard label="表数量" value={String(stats.table_count)} />
          <InfoCard label="活动连接" value={String(stats.active_connections)} />
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <Button variant="outline" onClick={handleBackup} disabled={backupLoading}>
          <Download className="h-4 w-4" /> {backupLoading ? '备份中...' : '备份数据库'}
        </Button>
        <Button variant="outline" onClick={handleCleanup} disabled={cleanupLoading}>
          <Trash2 className="h-4 w-4" /> {cleanupLoading ? '清理中...' : '清理旧数据'}
        </Button>
      </div>

      {/* Table List */}
      <Card>
        <CardHeader><CardTitle className="text-sm">数据表列表</CardTitle></CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[500px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">表名</th>
                <th className="px-4 py-3 text-right">行数</th>
                <th className="px-4 py-3 text-right">大小</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {tables.map(t => (
                <tr key={t.name} className="border-b last:border-0 hover:bg-accent/50">
                  <td className="px-4 py-2 font-mono text-xs">{t.name}</td>
                  <td className="px-4 py-2 text-right">{t.row_count.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right text-muted-foreground">{t.size}</td>
                  <td className="px-4 py-2">
                    <Button size="sm" variant="ghost" onClick={() => handleViewTable(t.name)}>
                      <Eye className="h-3.5 w-3.5" /> 查看
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>

      {/* Table Data Modal */}
      {viewTable && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between text-sm">
              <span>表数据: {viewTable} (前 100 行)</span>
              <Button size="sm" variant="ghost" onClick={() => { setViewTable(null); setTableData(null) }}>关闭</Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {tableLoading ? (
              <div className="text-muted-foreground text-center py-4">加载中...</div>
            ) : tableData ? (
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b">
                      {tableData.columns.map(c => (
                        <th key={c} className="px-2 py-1 text-left font-medium whitespace-nowrap">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.rows.map((row, i) => (
                      <tr key={i} className="border-b last:border-0">
                        {tableData.columns.map(c => (
                          <td key={c} className="px-2 py-1 max-w-[90px] sm:max-w-[200px] truncate">{String(row[c] ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-muted-foreground text-center py-4">无数据</div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ─── Roles Tab ───

function RolesTab() {
  const [roles, setRoles] = useState<RoleItem[]>([])
  const [permissions, setPermissions] = useState<PermissionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [editRole, setEditRole] = useState<RoleItem | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [permTarget, setPermTarget] = useState<RoleItem | null>(null)
  const [seeding, setSeeding] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const load = () => {
    setLoading(true)
    Promise.all([listRoles(), listPermissions()])
      .then(([r, p]) => { setRoles(r); setPermissions(p) })
      .catch(() => addToast('加载失败', 'error'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleSeed = async () => {
    if (!confirm('确认初始化默认权限和角色？（幂等操作，不会重复创建）')) return
    setSeeding(true)
    try {
      const res = await seedRbac()
      addToast(`初始化完成：${res.created_permissions} 条新权限，${res.created_roles} 个新角色`, 'success')
      load()
    } catch { addToast('初始化失败', 'error') }
    finally { setSeeding(false) }
  }

  const handleDelete = async (role: RoleItem) => {
    if (!confirm(`确认删除角色「${role.role_name}」？`)) return
    try {
      await deleteRole(role.id)
      addToast('角色删除成功', 'success')
      load()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '删除失败'
      addToast(msg, 'error')
    }
  }

  const filtered = roles.filter(r => {
    if (filter === 'active') return r.is_active
    if (filter === 'inactive') return !r.is_active
    return true
  })

  const activeCount = roles.filter(r => r.is_active).length
  const inactiveCount = roles.length - activeCount

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <InfoCard label="总角色数" value={String(roles.length)} />
        <InfoCard label="已启用" value={String(activeCount)} />
        <InfoCard label="已禁用" value={String(inactiveCount)} />
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1">
          {(['all', 'active', 'inactive'] as const).map(f => (
            <Button key={f} size="sm" variant={filter === f ? 'default' : 'outline'} onClick={() => setFilter(f)}>
              {f === 'all' ? '全部' : f === 'active' ? '启用' : '禁用'}
            </Button>
          ))}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleSeed} disabled={seeding}>
            <Key className="h-3.5 w-3.5" /> {seeding ? '初始化中...' : '初始化权限'}
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="h-3.5 w-3.5" /> 新增角色
          </Button>
          <Button size="sm" variant="ghost" onClick={load}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Roles Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[700px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">角色名称</th>
                <th className="px-4 py-3">角色编码</th>
                <th className="px-4 py-3">描述</th>
                <th className="px-4 py-3 text-center">权限数</th>
                <th className="px-4 py-3 text-center">状态</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => (
                <tr key={r.id} className="border-b last:border-0 hover:bg-accent/50">
                  <td className="px-4 py-2 font-medium">
                    <span className="flex items-center gap-1.5">
                      {r.is_system && <Lock className="h-3.5 w-3.5 text-amber-500" />}
                      {r.role_name}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{r.role_code}</td>
                  <td className="px-4 py-2 text-muted-foreground truncate max-w-[90px] sm:max-w-[200px]">{r.description}</td>
                  <td className="px-4 py-2 text-center">
                    <Badge variant="outline">{r.permission_count}</Badge>
                  </td>
                  <td className="px-4 py-2 text-center">
                    <Badge variant={r.is_active ? 'default' : 'secondary'}>
                      {r.is_active ? '启用' : '禁用'}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" title="编辑" onClick={() => setEditRole(r)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" title="权限分配" onClick={() => setPermTarget(r)}>
                        <Shield className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" title="删除" disabled={r.is_system}
                        onClick={() => handleDelete(r)}
                        className={r.is_system ? 'opacity-30' : 'text-destructive hover:text-destructive'}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">暂无角色数据，请先点击「初始化权限」</td></tr>
              )}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>

      {/* Dialogs */}
      {(showCreate || editRole) && (
        <RoleEditDialog
          role={editRole}
          onClose={() => { setShowCreate(false); setEditRole(null) }}
          onSaved={() => { setShowCreate(false); setEditRole(null); load() }}
        />
      )}
      {permTarget && (
        <PermissionAssignDialog
          role={permTarget}
          allPermissions={permissions}
          onClose={() => setPermTarget(null)}
          onSaved={() => { setPermTarget(null); load() }}
        />
      )}
    </div>
  )
}

// ─── Role Edit Dialog ───

function RoleEditDialog({ role, onClose, onSaved }: {
  role: RoleItem | null; onClose: () => void; onSaved: () => void
}) {
  const isEdit = !!role
  const [form, setForm] = useState({
    role_name: role?.role_name || '',
    role_code: role?.role_code || '',
    description: role?.description || '',
    is_active: role?.is_active ?? true,
  })
  const [saving, setSaving] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const handleSave = async () => {
    if (!form.role_name.trim() || !form.role_code.trim()) {
      addToast('角色名称和编码不能为空', 'error')
      return
    }
    setSaving(true)
    try {
      if (isEdit) {
        await updateRole(role!.id, { role_name: form.role_name, description: form.description, is_active: form.is_active })
      } else {
        await createRole(form)
      }
      addToast(isEdit ? '角色更新成功' : '角色创建成功', 'success')
      onSaved()
    } catch (e: unknown) {
      addToast(e instanceof Error ? e.message : '保存失败', 'error')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <Card className="w-[calc(100vw-2rem)] max-w-md" onClick={(e) => e.stopPropagation()}>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-sm">
            <span>{isEdit ? '编辑角色' : '新增角色'}</span>
            <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">角色名称 *</label>
            <Input value={form.role_name} onChange={(e) => setForm({ ...form, role_name: e.target.value })} placeholder="如: 交易管理员" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">角色编码 *</label>
            <Input value={form.role_code} disabled={isEdit}
              onChange={(e) => setForm({ ...form, role_code: e.target.value })}
              placeholder="如: trade_admin" className={isEdit ? 'opacity-60' : ''} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">描述</label>
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="角色描述..." />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            启用状态
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>取消</Button>
            <Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Permission Assign Dialog ───

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  api: 'API 接口权限',
  menu: '菜单导航权限',
  button: '按钮操作权限',
}

function PermissionAssignDialog({ role, allPermissions, onClose, onSaved }: {
  role: RoleItem; allPermissions: PermissionItem[]; onClose: () => void; onSaved: () => void
}) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [originalIds, setOriginalIds] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    getRolePermissions(role.id)
      .then((ids) => {
        const s = new Set(ids)
        setSelectedIds(new Set(s))
        setOriginalIds(s)
      })
      .finally(() => setLoading(false))
  }, [role.id])

  const grouped = allPermissions.reduce<Record<string, PermissionItem[]>>((acc, p) => {
    (acc[p.resource_type] ??= []).push(p)
    return acc
  }, {})

  const toggle = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const selectAllOfType = (type: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      grouped[type]?.forEach(p => next.add(p.id))
      return next
    })
  }

  const clearAllOfType = (type: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      grouped[type]?.forEach(p => next.delete(p.id))
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const toRemove = [...originalIds].filter(id => !selectedIds.has(id))
      const toAdd = [...selectedIds].filter(id => !originalIds.has(id))
      for (const id of toRemove) await revokePermission(role.id, id)
      for (const id of toAdd) await assignPermission(role.id, id)
      addToast(`权限更新成功（+${toAdd.length} / -${toRemove.length}）`, 'success')
      onSaved()
    } catch (e: unknown) {
      addToast(e instanceof Error ? e.message : '保存失败', 'error')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <Card className="w-[calc(100vw-2rem)] max-w-2xl max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm">
            <span>{role.role_name} — 权限分配</span>
            <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-y-auto flex-1 space-y-4">
          {loading ? (
            <div className="text-muted-foreground py-8 text-center">加载中...</div>
          ) : (
            ['api', 'menu', 'button'].map(type => {
              const perms = grouped[type] || []
              if (perms.length === 0) return null
              const selectedInType = perms.filter(p => selectedIds.has(p.id)).length
              return (
                <div key={type}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium">{RESOURCE_TYPE_LABELS[type] || type}</span>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" className="text-xs h-6 px-2" onClick={() => selectAllOfType(type)}>
                        <Check className="h-3 w-3" /> 全选
                      </Button>
                      <Button size="sm" variant="ghost" className="text-xs h-6 px-2" onClick={() => clearAllOfType(type)}>
                        <X className="h-3 w-3" /> 清空
                      </Button>
                      <Badge variant="outline" className="text-xs">{selectedInType}/{perms.length}</Badge>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                    {perms.map(p => (
                      <label key={p.id} className="flex items-start gap-2 rounded px-2 py-1.5 hover:bg-accent/50 cursor-pointer text-sm">
                        <input type="checkbox" className="mt-0.5" checked={selectedIds.has(p.id)} onChange={() => toggle(p.id)} />
                        <span>
                          <span className="font-medium">{p.permission_name}</span>
                          {p.description && <span className="text-xs text-muted-foreground ml-1">({p.description})</span>}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )
            })
          )}
        </CardContent>
        <div className="border-t px-4 py-3 flex items-center justify-between">
          <span className="text-sm text-muted-foreground">已选择 {selectedIds.size} 个权限</span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>取消</Button>
            <Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </div>
      </Card>
    </div>
  )
}

// ─── AiCoin Tab ───

function AicoinTab() {
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [showSecret, setShowSecret] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    getAicoinConfig()
      .then((cfg) => { setApiKey(cfg.api_key); setApiSecret(cfg.api_secret) })
      .catch(() => addToast('加载 AiCoin 配置失败', 'error'))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateAicoinConfig({ api_key: apiKey, api_secret: apiSecret })
      addToast('AiCoin 配置已保存', 'success')
    } catch { addToast('保存失败', 'error') }
    finally { setSaving(false) }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const res = await testAicoinConfig()
      addToast(`连接成功，共 ${res.coin_count} 个币种`, 'success')
    } catch (err: unknown) {
      addToast(extractError(err, '连接失败'), 'error')
    } finally { setTesting(false) }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-sm flex items-center gap-2"><Zap className="h-4 w-4" /> AiCoin API 配置</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">API Key</label>
            <Input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="输入 AiCoin API Key" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">API Secret</label>
            <div className="flex gap-2">
              <Input
                type={showSecret ? 'text' : 'password'}
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                placeholder="输入 AiCoin API Secret"
                className="flex-1"
              />
              <Button variant="outline" size="sm" onClick={() => setShowSecret(!showSecret)}>
                <Eye className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="flex gap-2 pt-2">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存配置'}
            </Button>
            <Button variant="outline" onClick={handleTest} disabled={testing}>
              {testing ? '测试中...' : '测试连接'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── SSL Tab ───

function SSLTab() {
  const [certs, setCerts] = useState<SSLCert[]>([])
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)
  const [scanning, setScanning] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = () => {
    setLoading(true)
    listSSLCerts().then(setCerts).finally(() => setLoading(false))
  }

  useEffect(reload, [])

  const handleDeploy = async (id: number) => {
    try {
      await deploySSLCert(id)
      addToast('证书部署成功', 'success')
      reload()
    } catch (err: unknown) {
      addToast(extractError(err, '部署失败'), 'error')
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确认删除此证书?')) return
    try {
      await deleteSSLCert(id)
      addToast('已删除', 'success')
      reload()
    } catch (err: unknown) {
      addToast(extractError(err, '删除失败'), 'error')
    }
  }

  const daysLeft = (expiresAt: string | null) => {
    if (!expiresAt) return null
    const diff = (new Date(expiresAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
    return Math.max(0, Math.floor(diff))
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" disabled={scanning} onClick={async () => {
          setScanning(true)
          try {
            const res = await scanLetsEncryptCerts()
            if (res.added > 0) {
              addToast(`导入 ${res.added} 个证书: ${res.domains.join(', ')}`, 'success')
              reload()
            } else {
              addToast(`扫描完成，无新证书 (已扫描 ${res.scanned} 个目录)`, 'success')
            }
          } catch (err: unknown) { addToast(extractError(err, '扫描失败'), 'error') }
          finally { setScanning(false) }
        }}>
          <ScanSearch className="h-4 w-4" /> {scanning ? '扫描中...' : '扫描 Let\'s Encrypt'}
        </Button>
        <Button size="sm" onClick={() => setShowUpload(!showUpload)}>
          <Plus className="h-4 w-4" /> 上传证书
        </Button>
      </div>

      {showUpload && (
        <UploadCertDialog
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); reload(); addToast('证书上传成功', 'success') }}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[850px]">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">域名</th>
                <th className="px-4 py-3">签发者</th>
                <th className="px-4 py-3">到期时间</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">部署</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : certs.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">暂无证书</td></tr>
              ) : (
                certs.map((c) => {
                  const dl = daysLeft(c.expires_at)
                  return (
                    <tr key={c.id} className="border-b last:border-0 hover:bg-accent/50">
                      <td className="px-4 py-3 font-medium">{c.cert_name}</td>
                      <td className="px-4 py-3">{c.domain_name}</td>
                      <td className="px-4 py-3 text-muted-foreground">{c.issuer || '-'}</td>
                      <td className="px-4 py-3">
                        {c.expires_at ? (
                          <span className={dl !== null && dl <= 7 ? 'text-negative' : dl !== null && dl <= 30 ? 'text-warning' : ''}>
                            {new Date(c.expires_at).toLocaleDateString('zh-CN')}
                            {dl !== null && ` (${dl}天)`}
                          </span>
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={c.status === 'active' ? 'success' : 'destructive'}>{c.status}</Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={c.is_deployed ? 'success' : 'secondary'}>
                          {c.is_deployed ? '已部署' : '未部署'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-1">
                          <Button size="sm" variant="ghost" onClick={() => handleDeploy(c.id)} title="部署">
                            <Rocket className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => handleDelete(c.id)} title="删除">
                            <Trash2 className="h-3.5 w-3.5 text-negative" />
                          </Button>
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

function UploadCertDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [form, setForm] = useState({ cert_name: '', domain_name: '', cert_content: '', key_content: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleFile = (field: 'cert_content' | 'key_content') => (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setForm({ ...form, [field]: reader.result as string })
    reader.readAsText(file)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await uploadSSLCert(form)
      onUploaded()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '上传失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">上传 SSL 证书</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">证书名称</label>
              <Input value={form.cert_name} onChange={(e) => setForm({ ...form, cert_name: e.target.value })} required />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">域名</label>
              <Input value={form.domain_name} onChange={(e) => setForm({ ...form, domain_name: e.target.value })} required />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">证书文件 (.pem / .crt)</label>
            <div className="flex gap-2">
              <Input type="file" accept=".pem,.crt" onChange={handleFile('cert_content')} />
              {form.cert_content && <Badge variant="success">已选择</Badge>}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">私钥文件 (.key / .pem)</label>
            <div className="flex gap-2">
              <Input type="file" accept=".pem,.key" onChange={handleFile('key_content')} />
              {form.key_content && <Badge variant="success">已选择</Badge>}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">或粘贴证书 PEM 内容</label>
            <textarea
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              rows={4}
              value={form.cert_content}
              onChange={(e) => setForm({ ...form, cert_content: e.target.value })}
              placeholder="-----BEGIN CERTIFICATE-----"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">或粘贴私钥 PEM 内容</label>
            <textarea
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              rows={4}
              value={form.key_content}
              onChange={(e) => setForm({ ...form, key_content: e.target.value })}
              placeholder="-----BEGIN PRIVATE KEY-----"
            />
          </div>
          {error && <p className="text-sm text-negative">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>
              <Upload className="h-4 w-4" />
              {saving ? '上传中...' : '上传'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// ─── Proxies Tab ───

type ProxySubTab = 'proxies' | 'ipipgo'

function ProxiesMainTab() {
  const [subTab, setSubTab] = useState<ProxySubTab>('proxies')

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <button onClick={() => setSubTab('proxies')}
          className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
            subTab === 'proxies' ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Globe className="h-4 w-4" /> 代理池
        </button>
        <button onClick={() => setSubTab('ipipgo')}
          className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
            subTab === 'ipipgo' ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Server className="h-4 w-4" /> IPIPGO 订单
        </button>
      </div>

      {subTab === 'proxies' && <ProxyPoolTab />}
      {subTab === 'ipipgo' && <IpipgoTab />}
    </div>
  )
}

function ProxyPoolTab() {
  const [proxies, setProxies] = useState<ProxyItem[]>([])
  const [bindings, setBindings] = useState<ProxyBinding[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [showBind, setShowBind] = useState(false)
  const [checking, setChecking] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = () => {
    setLoading(true)
    Promise.all([listProxies(), listProxyBindings()])
      .then(([p, b]) => { setProxies(p); setBindings(b) })
      .finally(() => setLoading(false))
  }

  useEffect(reload, [])

  const handleHealthCheck = async () => {
    setChecking(true)
    try {
      const result = await healthCheckProxies()
      addToast(`健康检查完成: ${result.checked} 个代理`, 'success')
      reload()
    } catch { addToast('健康检查失败', 'error') }
    finally { setChecking(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={handleHealthCheck} disabled={checking}>
          <HeartPulse className="h-4 w-4" /> {checking ? '检查中...' : '健康检查'}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setShowBind(!showBind)}>
          <Link2 className="h-4 w-4" /> 绑定
        </Button>
        <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
          <Plus className="h-4 w-4" /> 添加代理
        </Button>
      </div>

      {showCreate && (
        <CreateProxyDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); reload(); addToast('代理添加成功', 'success') }}
        />
      )}

      {showBind && (
        <BindDialog
          proxies={proxies}
          bindings={bindings}
          onClose={() => setShowBind(false)}
          onChanged={() => { reload(); addToast('操作成功', 'success') }}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[850px]">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">地址</th>
                <th className="px-4 py-3">协议</th>
                <th className="px-4 py-3">来源</th>
                <th className="px-4 py-3">健康</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">区域</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : proxies.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">暂无代理</td></tr>
              ) : (
                proxies.map((p) => (
                  <tr key={p.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 font-medium">{p.name}</td>
                    <td className="px-4 py-3 font-mono text-xs">{p.host}:{p.port}</td>
                    <td className="px-4 py-3">{p.protocol}</td>
                    <td className="px-4 py-3">{p.provider}</td>
                    <td className="px-4 py-3">
                      <span className={p.health_score >= 80 ? 'text-positive' : p.health_score >= 50 ? 'text-warning' : 'text-negative'}>
                        {p.health_score}%
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={p.status === 'active' ? 'success' : p.status === 'error' ? 'destructive' : 'secondary'}>
                        {p.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{p.region || '-'}</td>
                    <td className="px-4 py-3">
                      <Button size="sm" variant="ghost" onClick={async () => {
                        if (!confirm('确认删除?')) return
                        try {
                          await deleteProxy(p.id)
                          reload()
                          addToast('已删除', 'success')
                        } catch (err: unknown) { addToast(extractError(err, '删除失败'), 'error') }
                      }}>
                        <Trash2 className="h-3.5 w-3.5 text-negative" />
                      </Button>
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

function IpipgoTab() {
  const [orders, setOrders] = useState<IpipgoOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = () => {
    setLoading(true)
    getIpipgoOrders().then(setOrders).finally(() => setLoading(false))
  }

  useEffect(reload, [])

  const handleSync = async () => {
    setSyncing(true)
    try {
      const result = await syncIpipgoOrders()
      addToast(`同步完成: ${result.synced} 个订单`, 'success')
      reload()
    } catch { addToast('同步失败', 'error') }
    finally { setSyncing(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={handleSync} disabled={syncing}>
          <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
          {syncing ? '同步中...' : '同步订单'}
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[850px]">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3">订单号</th>
                <th className="px-4 py-3">产品</th>
                <th className="px-4 py-3">IP</th>
                <th className="px-4 py-3">协议</th>
                <th className="px-4 py-3">区域</th>
                <th className="px-4 py-3">到期时间</th>
                <th className="px-4 py-3">剩余天数</th>
                <th className="px-4 py-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : orders.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">暂无订单</td></tr>
              ) : (
                orders.map((o) => (
                  <tr key={o.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 font-mono text-xs">{o.order_no}</td>
                    <td className="px-4 py-3">{o.product_name || '-'}</td>
                    <td className="px-4 py-3 font-mono text-xs">{o.ip_address ? `${o.ip_address}:${o.port}` : '-'}</td>
                    <td className="px-4 py-3">{o.protocol || '-'}</td>
                    <td className="px-4 py-3">{o.region || '-'}</td>
                    <td className="px-4 py-3">{o.end_date ? new Date(o.end_date).toLocaleDateString('zh-CN') : '-'}</td>
                    <td className="px-4 py-3">
                      {o.days_left !== null ? (
                        <span className={o.days_left <= 7 ? 'text-negative font-medium' : o.days_left <= 30 ? 'text-warning' : 'text-positive'}>
                          {o.days_left} 天
                        </span>
                      ) : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={o.status === 'active' ? 'success' : o.status === 'expired' ? 'destructive' : 'secondary'}>
                        {o.status}
                      </Badge>
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

function CreateProxyDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({ name: '', host: '', port: 0, username: '', password: '', protocol: 'http', provider: 'custom', region: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.name.trim()) { setError('请填写名称'); return }
    if (!form.host.trim()) { setError('请填写主机地址'); return }
    if (!form.port || form.port <= 0) { setError('请填写有效端口'); return }
    setSaving(true)
    try { await createProxy(form); onCreated() }
    catch (err: unknown) { setError(extractError(err, '添加失败')) }
    finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">添加代理</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">名称</label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">主机</label>
            <Input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} required />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">端口</label>
            <Input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: parseInt(e.target.value) || 0 })} required />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">用户名</label>
            <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">密码</label>
            <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="off" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">协议</label>
            <select className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm" value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })}>
              <option value="http">HTTP</option>
              <option value="socks5">SOCKS5</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">区域</label>
            <Input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} />
          </div>
          {error && <p className="col-span-full text-sm text-negative">{error}</p>}
          <div className="col-span-full flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>取消</Button>
            <Button type="submit" disabled={saving}>{saving ? '添加中...' : '添加'}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function BindDialog({ proxies, bindings, onClose, onChanged }: {
  proxies: ProxyItem[]; bindings: ProxyBinding[]; onClose: () => void; onChanged: () => void
}) {
  const [accountId, setAccountId] = useState('')
  const [proxyId, setProxyId] = useState('')
  const [error, setError] = useState('')

  const handleBind = async () => {
    setError('')
    if (!accountId) { setError('请输入子账户 ID'); return }
    if (!proxyId) { setError('请选择代理'); return }
    try {
      await bindProxy({ sub_account_id: parseInt(accountId), proxy_id: parseInt(proxyId) })
      onChanged()
    } catch (err: unknown) { setError(extractError(err, '绑定失败')) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">代理绑定管理</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <Input placeholder="子账户 ID" value={accountId} onChange={(e) => setAccountId(e.target.value)} />
          <select className="flex h-9 rounded-md border border-input px-3 text-sm" value={proxyId} onChange={(e) => setProxyId(e.target.value)}>
            <option value="">选择代理</option>
            {proxies.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.host}:{p.port})</option>)}
          </select>
          <Button onClick={handleBind}>绑定</Button>
          <Button variant="ghost" onClick={onClose}>关闭</Button>
        </div>
        {error && <p className="text-sm text-negative">{error}</p>}
        {bindings.length > 0 && (
          <div className="overflow-x-auto">
          <table className="w-full text-sm md:min-w-[400px]">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-3 py-2">账户</th>
                <th className="px-3 py-2">代理</th>
                <th className="px-3 py-2">平台</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {bindings.map((b) => (
                <tr key={b.id} className="border-b last:border-0">
                  <td className="px-3 py-2">{b.account_note || `#${b.sub_account_id}`}</td>
                  <td className="px-3 py-2">{b.proxy_name || `#${b.proxy_id}`}</td>
                  <td className="px-3 py-2">{b.platform}</td>
                  <td className="px-3 py-2">
                    <Button size="sm" variant="ghost" onClick={async () => {
                      try { await unbindProxy(b.id); onChanged() }
                      catch (err: unknown) { setError(extractError(err, '解绑失败')) }
                    }}>
                      <Trash2 className="h-3.5 w-3.5 text-negative" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Shared ───

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-3">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-0.5 text-sm font-medium">{value}</p>
      </CardContent>
    </Card>
  )
}
