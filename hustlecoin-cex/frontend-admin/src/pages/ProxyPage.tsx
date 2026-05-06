import { useEffect, useState } from 'react'
import {
  listProxies, createProxy, deleteProxy, healthCheckProxies,
  listProxyBindings, bindProxy, unbindProxy,
  getIpipgoOrders, syncIpipgoOrders,
  type ProxyItem, type ProxyBinding, type IpipgoOrder,
} from '@/api/admin'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { extractError } from '@/api/client'
import { Plus, Trash2, HeartPulse, Link2, Globe, Server, RefreshCw } from 'lucide-react'

type Tab = 'proxies' | 'ipipgo'

export function ProxyPage() {
  const [tab, setTab] = useState<Tab>('proxies')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">代理管理</h1>

      <div className="flex gap-1 border-b">
        <button onClick={() => setTab('proxies')}
          className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm transition-colors ${
            tab === 'proxies' ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Globe className="h-4 w-4" /> 代理池
        </button>
        <button onClick={() => setTab('ipipgo')}
          className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm transition-colors ${
            tab === 'ipipgo' ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Server className="h-4 w-4" /> IPIPGO 订单
        </button>
      </div>

      {tab === 'proxies' && <ProxiesTab />}
      {tab === 'ipipgo' && <IpipgoTab />}
    </div>
  )
}

function ProxiesTab() {
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
          <table className="w-full text-sm">
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
          <table className="w-full text-sm">
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
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Shared Dialogs ───

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
        <form onSubmit={handleSubmit} className="grid grid-cols-3 gap-3">
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
          {error && <p className="col-span-3 text-sm text-negative">{error}</p>}
          <div className="col-span-3 flex justify-end gap-2">
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
          <table className="w-full text-sm">
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
        )}
      </CardContent>
    </Card>
  )
}
