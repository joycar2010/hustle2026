import { useEffect, useState, useCallback } from 'react'
import {
  getFeishuConfig, updateFeishuConfig, testFeishuSend, getFeishuStatus, listUsers,
  updateUserFeishuConfig, deleteUserFeishuConfig,
  getEmailConfig, updateEmailConfig, testEmailSend,
  listNotificationTemplates, updateNotificationTemplate, createNotificationTemplate, deleteNotificationTemplate, testNotificationTemplate,
  listNotificationLogs, broadcastNotification, listSounds,
  type FeishuConfigItem, type FeishuStatus, type EmailConfigItem, type NotificationTemplate, type NotificationLog, type SoundPreset, type UserItem,
} from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import {
  Bell, Settings, FileText, Send, CheckCircle, XCircle, Mail, Volume2,
  Plus, Trash2, Pencil, X, Megaphone,
} from 'lucide-react'

type Tab = 'feishu' | 'email' | 'broadcast' | 'templates' | 'logs' | 'sounds'

export function NotifyPage() {
  const [tab, setTab] = useState<Tab>('feishu')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">通知服务</h1>
      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <TabBtn active={tab === 'feishu'} onClick={() => setTab('feishu')} icon={Bell} label="飞书机器人" />
        <TabBtn active={tab === 'email'} onClick={() => setTab('email')} icon={Mail} label="邮件配置" />
        <TabBtn active={tab === 'broadcast'} onClick={() => setTab('broadcast')} icon={Megaphone} label="网站通知" />
        <TabBtn active={tab === 'templates'} onClick={() => setTab('templates')} icon={Settings} label="模板管理" />
        <TabBtn active={tab === 'logs'} onClick={() => setTab('logs')} icon={FileText} label="发送日志" />
        <TabBtn active={tab === 'sounds'} onClick={() => setTab('sounds')} icon={Volume2} label="提醒声音" />
      </div>
      {tab === 'feishu' && <FeishuTab />}
      {tab === 'email' && <EmailTab />}
      {tab === 'broadcast' && <BroadcastTab />}
      {tab === 'templates' && <TemplatesTab />}
      {tab === 'logs' && <LogsTab />}
      {tab === 'sounds' && <SoundsTab />}
    </div>
  )
}

function TabBtn({ active, onClick, icon: Icon, label }: {
  active: boolean; onClick: () => void; icon: React.ComponentType<{ className?: string }>; label: string
}) {
  return (
    <button onClick={onClick} className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
      active ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
    }`}>
      <Icon className="h-4 w-4" />
      {label}
    </button>
  )
}

// ─── Feishu Tab ───

function FeishuTab() {
  const [configs, setConfigs] = useState<FeishuConfigItem[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({
    app_id: '', app_secret: '', webhook_url: '', secret_key: '',
    alert_interval_sec: 5, alert_count: 1, margin_rate_alert: 30, leverage_risk_alert: 1.3,
    enable_transfer_fail_alert: true, enable_new_borrow_alert: true,
  })
  const [showAppSecret, setShowAppSecret] = useState(false)
  const [feishuStatus, setFeishuStatus] = useState<FeishuStatus>({ connected: false, token_expires_at: null, error: null })
  const [users, setUsers] = useState<UserItem[]>([])
  const [testRecipient, setTestRecipient] = useState('')
  const [testRecipientManual, setTestRecipientManual] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [checking, setChecking] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    Promise.all([getFeishuConfig(), listUsers()]).then(([data, userList]) => {
      setConfigs(data)
      setUsers(userList)
      const g = data.find(c => c.is_global)
      if (g) setForm({
        app_id: g.app_id || '', app_secret: g.app_secret || '',
        webhook_url: g.webhook_url || '', secret_key: g.secret_key || '',
        alert_interval_sec: g.alert_interval_sec, alert_count: g.alert_count,
        margin_rate_alert: g.margin_rate_alert, leverage_risk_alert: g.leverage_risk_alert,
        enable_transfer_fail_alert: g.enable_transfer_fail_alert, enable_new_borrow_alert: g.enable_new_borrow_alert,
      })
    }).finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  const handleCheckStatus = useCallback(async () => {
    setChecking(true)
    try { const s = await getFeishuStatus(); setFeishuStatus(s) }
    catch { setFeishuStatus({ connected: false, token_expires_at: null, error: '检测失败' }) }
    finally { setChecking(false) }
  }, [])

  useEffect(() => { if (!loading) handleCheckStatus() }, [loading, handleCheckStatus])

  const handleSave = async () => {
    setSaving(true)
    try { await updateFeishuConfig(form); addToast('配置已保存', 'success'); reload() }
    catch (err: unknown) { addToast(extractError(err, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  const handleTest = async () => {
    const recipient = testRecipient || testRecipientManual
    if (!recipient) { addToast('请选择或输入测试接收人', 'error'); return }
    setTesting(true)
    try {
      const res = await testFeishuSend(recipient)
      addToast(res.status === 'sent' ? '测试消息已发送' : `发送失败: ${res.detail || res.error}`, res.status === 'sent' ? 'success' : 'error')
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      addToast(detail || '测试失败', 'error')
    }
    finally { setTesting(false) }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm">飞书机器人配置</CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">配置飞书应用凭证，用于发送交易通知和告警</p>
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${feishuStatus.connected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
              <span className={`text-xs font-medium ${feishuStatus.connected ? 'text-green-500' : 'text-red-500'}`}>
                {feishuStatus.connected ? '已连接' : '未连接'}
              </span>
              {feishuStatus.token_expires_at && (
                <span className="text-xs text-muted-foreground ml-1">
                  Token 到期: {new Date(feishuStatus.token_expires_at).toLocaleString('zh-CN')}
                </span>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <form autoComplete="off">
            <input type="text" name="prevent_autofill_u" autoComplete="username" className="hidden" tabIndex={-1} />
            <input type="password" name="prevent_autofill_p" autoComplete="new-password" className="hidden" tabIndex={-1} />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">App ID</label>
                <Input value={form.app_id} onChange={(e) => setForm({ ...form, app_id: e.target.value })}
                  placeholder="cli_xxxxxxxxxxxxxxxxxx" autoComplete="off" name="feishu_app_id_field" />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">App Secret</label>
                <div className="relative">
                  <Input type={showAppSecret ? 'text' : 'password'} value={form.app_secret}
                    onChange={(e) => setForm({ ...form, app_secret: e.target.value })}
                    placeholder="••••••••••••••••" autoComplete="new-password" name="feishu_app_secret_field" />
                  <button type="button" onClick={() => setShowAppSecret(!showAppSecret)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs">
                    {showAppSecret ? '隐藏' : '显示'}
                  </button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">告警间隔 (秒)</label>
                <Input type="number" value={form.alert_interval_sec} onChange={(e) => setForm({ ...form, alert_interval_sec: parseInt(e.target.value) || 5 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">单周期告警次数</label>
                <Input type="number" value={form.alert_count} onChange={(e) => setForm({ ...form, alert_count: parseInt(e.target.value) || 1 })} />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">合约爆仓率预警 (%)</label>
                <Input type="number" value={form.margin_rate_alert} onChange={(e) => setForm({ ...form, margin_rate_alert: parseFloat(e.target.value) || 30 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">杠杆风险率预警</label>
                <Input type="number" step="0.01" value={form.leverage_risk_alert} onChange={(e) => setForm({ ...form, leverage_risk_alert: parseFloat(e.target.value) || 1.3 })} />
              </div>
            </div>
            <div className="flex items-center gap-4 mt-4">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.enable_transfer_fail_alert} onChange={(e) => setForm({ ...form, enable_transfer_fail_alert: e.target.checked })} className="accent-primary" />
                划转失败提醒
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.enable_new_borrow_alert} onChange={(e) => setForm({ ...form, enable_new_borrow_alert: e.target.checked })} className="accent-primary" />
                新增借币提醒
              </label>
            </div>
          </form>

          <div className="border-t pt-4 mt-4">
            <label className="text-xs text-muted-foreground mb-1 block">测试接收人</label>
            <div className="flex gap-2">
              <select value={testRecipient} onChange={(e) => setTestRecipient(e.target.value)}
                className="flex-1 h-9 rounded-md border border-input px-3 py-1 text-sm">
                <option value="">-- 手动输入 --</option>
                {users.filter(u => u.feishu_open_id || u.feishu_phone).map(u => (
                  <option key={u.id} value={u.feishu_open_id || u.feishu_phone || ''}>
                    {u.username}{u.feishu_open_id ? ' (Open ID)' : u.feishu_phone ? ' (手机号)' : ''}
                  </option>
                ))}
              </select>
              {!testRecipient && (
                <Input value={testRecipientManual} onChange={(e) => setTestRecipientManual(e.target.value)}
                  placeholder="open_id 或手机号" className="flex-1" />
              )}
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存配置'}</Button>
            <Button variant="outline" onClick={handleCheckStatus} disabled={checking}>
              {checking ? '检测中...' : '检测连接'}
            </Button>
            <Button variant="outline" onClick={handleTest} disabled={testing}>
              <Send className="h-4 w-4" /> {testing ? '发送中...' : '发送测试'}
            </Button>
          </div>
        </CardContent>
      </Card>
      <UserFeishuConfigSection configs={configs} users={users} onRefresh={reload} />
    </div>
  )
}

// ─── User-level Feishu Config Management ───

function UserFeishuConfigSection({ configs, users, onRefresh }: {
  configs: FeishuConfigItem[]; users: UserItem[]; onRefresh: () => void
}) {
  const [editing, setEditing] = useState<{ mode: 'create' | 'edit'; config?: FeishuConfigItem } | null>(null)
  const addToast = useToastStore((s) => s.addToast)
  const userConfigs = configs.filter(c => !c.is_global)

  const handleDelete = async (c: FeishuConfigItem) => {
    if (!c.user_id || !confirm(`确定删除用户 ${c.username || c.user_id} 的独立配置？\n删除后将使用全局配置。`)) return
    try { await deleteUserFeishuConfig(c.user_id); addToast('已删除', 'success'); onRefresh() }
    catch (err: unknown) { addToast(extractError(err, '删除失败'), 'error') }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm">用户级配置</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">为用户配置独立的飞书告警参数，未配置的用户使用全局配置</p>
          </div>
          <Button size="sm" onClick={() => setEditing({ mode: 'create' })}>
            <Plus className="h-4 w-4" /> 新增
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {userConfigs.length === 0 ? (
          <div className="text-center text-muted-foreground text-sm py-8">暂无用户级配置，所有用户使用全局配置</div>
        ) : (
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-3">用户</th>
                <th className="px-3 py-3">App ID</th>
                <th className="px-3 py-3">告警间隔</th>
                <th className="px-3 py-3">爆仓率</th>
                <th className="px-3 py-3">杠杆风险</th>
                <th className="px-3 py-3">划转</th>
                <th className="px-3 py-3">借币</th>
                <th className="px-3 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {userConfigs.map(c => (
                <tr key={c.id} className="border-b last:border-0 hover:bg-accent/50">
                  <td className="px-3 py-2.5 font-medium">{c.username || `用户 #${c.user_id}`}</td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground font-mono truncate max-w-[120px]">{c.app_id || c.webhook_url || '-'}</td>
                  <td className="px-3 py-2.5">{c.alert_interval_sec}s / {c.alert_count}次</td>
                  <td className="px-3 py-2.5">{c.margin_rate_alert}%</td>
                  <td className="px-3 py-2.5">{c.leverage_risk_alert}</td>
                  <td className="px-3 py-2.5">{c.enable_transfer_fail_alert ? <CheckCircle className="h-4 w-4 text-positive" /> : <XCircle className="h-4 w-4 text-muted-foreground" />}</td>
                  <td className="px-3 py-2.5">{c.enable_new_borrow_alert ? <CheckCircle className="h-4 w-4 text-positive" /> : <XCircle className="h-4 w-4 text-muted-foreground" />}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing({ mode: 'edit', config: c })}><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button size="sm" variant="ghost" onClick={() => handleDelete(c)}><Trash2 className="h-3.5 w-3.5 text-negative" /></Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </CardContent>
      {editing && (
        <UserFeishuConfigDialog
          mode={editing.mode}
          config={editing.config}
          users={users}
          existingUserIds={userConfigs.map(c => c.user_id).filter((id): id is number => id !== null)}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onRefresh() }}
        />
      )}
    </Card>
  )
}

function UserFeishuConfigDialog({ mode, config, users, existingUserIds, onClose, onSaved }: {
  mode: 'create' | 'edit'
  config?: FeishuConfigItem
  users: UserItem[]
  existingUserIds: number[]
  onClose: () => void
  onSaved: () => void
}) {
  const [userId, setUserId] = useState(config?.user_id || 0)
  const [form, setForm] = useState({
    app_id: config?.app_id || '',
    app_secret: config?.app_secret || '',
    webhook_url: config?.webhook_url || '',
    secret_key: config?.secret_key || '',
    alert_interval_sec: config?.alert_interval_sec ?? 5,
    alert_count: config?.alert_count ?? 1,
    margin_rate_alert: config?.margin_rate_alert ?? 30,
    leverage_risk_alert: config?.leverage_risk_alert ?? 1.3,
    enable_transfer_fail_alert: config?.enable_transfer_fail_alert ?? true,
    enable_new_borrow_alert: config?.enable_new_borrow_alert ?? true,
  })
  const [showSecret, setShowSecret] = useState(false)
  const [saving, setSaving] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const availableUsers = users.filter(u => !existingUserIds.includes(u.id))

  const handleSave = async () => {
    const targetUserId = mode === 'edit' ? config?.user_id : userId
    if (!targetUserId) { addToast('请选择用户', 'error'); return }
    setSaving(true)
    try {
      await updateUserFeishuConfig(targetUserId, form)
      addToast('用户配置已保存', 'success')
      onSaved()
    } catch (err: unknown) { addToast(extractError(err, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <Card className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm">{mode === 'create' ? '新增用户飞书配置' : `编辑: ${config?.username || `用户 #${config?.user_id}`}`}</CardTitle>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <form autoComplete="off">
            <input type="text" name="prevent_uf_u" autoComplete="username" className="hidden" tabIndex={-1} />
            <input type="password" name="prevent_uf_p" autoComplete="new-password" className="hidden" tabIndex={-1} />

            {mode === 'create' ? (
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">选择用户</label>
                <select value={userId} onChange={(e) => setUserId(parseInt(e.target.value) || 0)}
                  className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm">
                  <option value={0}>-- 请选择 --</option>
                  {availableUsers.map(u => <option key={u.id} value={u.id}>{u.username} (ID: {u.id})</option>)}
                </select>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground mb-2">用户: <strong className="text-foreground">{config?.username || `#${config?.user_id}`}</strong></div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">App ID</label>
                <Input value={form.app_id} onChange={(e) => setForm({ ...form, app_id: e.target.value })}
                  placeholder="cli_xxx (可选)" autoComplete="off" name="uf_app_id" />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">App Secret</label>
                <div className="relative">
                  <Input type={showSecret ? 'text' : 'password'} value={form.app_secret}
                    onChange={(e) => setForm({ ...form, app_secret: e.target.value })}
                    placeholder="可选" autoComplete="new-password" name="uf_app_secret" />
                  <button type="button" onClick={() => setShowSecret(!showSecret)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs">
                    {showSecret ? '隐藏' : '显示'}
                  </button>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Webhook URL</label>
                <Input value={form.webhook_url} onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
                  placeholder="可选" autoComplete="off" name="uf_webhook" />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Secret Key</label>
                <Input value={form.secret_key} onChange={(e) => setForm({ ...form, secret_key: e.target.value })}
                  placeholder="可选" autoComplete="off" name="uf_secret_key" />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">告警间隔 (秒)</label>
                <Input type="number" value={form.alert_interval_sec} onChange={(e) => setForm({ ...form, alert_interval_sec: parseInt(e.target.value) || 5 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">告警次数</label>
                <Input type="number" value={form.alert_count} onChange={(e) => setForm({ ...form, alert_count: parseInt(e.target.value) || 1 })} />
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">爆仓率预警 (%)</label>
                <Input type="number" value={form.margin_rate_alert} onChange={(e) => setForm({ ...form, margin_rate_alert: parseFloat(e.target.value) || 30 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">杠杆风险率</label>
                <Input type="number" step="0.01" value={form.leverage_risk_alert} onChange={(e) => setForm({ ...form, leverage_risk_alert: parseFloat(e.target.value) || 1.3 })} />
              </div>
            </div>
            <div className="flex items-center gap-4 mt-3">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.enable_transfer_fail_alert} onChange={(e) => setForm({ ...form, enable_transfer_fail_alert: e.target.checked })} className="accent-primary" />
                划转失败提醒
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.enable_new_borrow_alert} onChange={(e) => setForm({ ...form, enable_new_borrow_alert: e.target.checked })} className="accent-primary" />
                新增借币提醒
              </label>
            </div>
          </form>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose}>取消</Button>
            <Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Email Tab ───

function EmailTab() {
  const [form, setForm] = useState<EmailConfigItem>({ smtp_host: '', smtp_port: 465, smtp_user: '', smtp_password: '', smtp_from: '', use_ssl: true, is_enabled: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    getEmailConfig().then(setForm).finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try { await updateEmailConfig(form as unknown as Record<string, unknown>); addToast('邮件配置已保存', 'success') }
    catch (err: unknown) { addToast(extractError(err, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  const handleTest = async () => {
    setTesting(true)
    try { const res = await testEmailSend(); addToast(res.status === 'sent' ? '测试邮件已发送' : '发送失败', res.status === 'sent' ? 'success' : 'error') }
    catch (e: unknown) { addToast((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '测试失败', 'error') }
    finally { setTesting(false) }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">邮件发送配置 (SMTP)</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <form autoComplete="off">
          <input type="text" name="prevent_email_autofill_u" autoComplete="username" className="hidden" tabIndex={-1} />
          <input type="password" name="prevent_email_autofill_p" autoComplete="new-password" className="hidden" tabIndex={-1} />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">SMTP 服务器</label>
              <Input value={form.smtp_host} onChange={(e) => setForm({ ...form, smtp_host: e.target.value })} placeholder="smtp.example.com" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">端口</label>
              <Input type="number" value={form.smtp_port} onChange={(e) => setForm({ ...form, smtp_port: parseInt(e.target.value) || 465 })} />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">用户名</label>
              <Input value={form.smtp_user} onChange={(e) => setForm({ ...form, smtp_user: e.target.value })}
                autoComplete="off" name="smtp_user_field" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">密码</label>
              <Input type="password" value={form.smtp_password} onChange={(e) => setForm({ ...form, smtp_password: e.target.value })}
                autoComplete="new-password" name="smtp_password_field" />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">发件人地址</label>
              <Input value={form.smtp_from} onChange={(e) => setForm({ ...form, smtp_from: e.target.value })}
                placeholder="noreply@example.com" autoComplete="off" name="smtp_from_field" />
            </div>
            <div className="flex items-end gap-4 pb-1">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.use_ssl} onChange={(e) => setForm({ ...form, use_ssl: e.target.checked })} className="accent-primary" />
                SSL 加密
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input type="checkbox" checked={form.is_enabled} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} className="accent-primary" />
                启用邮件通知
              </label>
            </div>
          </div>
        </form>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存配置'}</Button>
          <Button variant="outline" onClick={handleTest} disabled={testing || !form.is_enabled}>
            <Send className="h-4 w-4" /> {testing ? '发送中...' : '测试邮件'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Broadcast Tab ───

function BroadcastTab() {
  const [form, setForm] = useState({ title: '', content: '', priority: 2, color: '#3b82f6', blink: false, sound: 'none' })
  const [sounds, setSounds] = useState<SoundPreset[]>([])
  const [sending, setSending] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => { listSounds().then(setSounds).catch(() => {}) }, [])

  const colorPresets = [
    { label: 'P1 红', value: '#ef4444' },
    { label: 'P2 蓝', value: '#3b82f6' },
    { label: 'P3 绿', value: '#22c55e' },
    { label: '橙', value: '#f59e0b' },
    { label: '紫', value: '#8b5cf6' },
    { label: '灰', value: '#6b7280' },
  ]

  const handleSend = async () => {
    if (!form.title.trim() || !form.content.trim()) { addToast('请填写标题和内容', 'error'); return }
    setSending(true)
    try { await broadcastNotification(form); addToast('通知已广播', 'success'); setForm({ ...form, title: '', content: '' }) }
    catch (err: unknown) { addToast(extractError(err, '广播失败'), 'error') }
    finally { setSending(false) }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">网站通知推送 (跑马灯)</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">通知标题</label>
          <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="通知标题" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">通知内容</label>
          <textarea value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} placeholder="通知内容，将在交易面板跑马灯中显示"
            className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring min-h-[80px]" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">优先级</label>
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value) })}
              className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm">
              <option value={1}>P1 紧急</option>
              <option value={2}>P2 重要</option>
              <option value={3}>P3 普通</option>
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">显示颜色</label>
            <div className="flex gap-1 flex-wrap">
              {colorPresets.map(c => (
                <button key={c.value} onClick={() => setForm({ ...form, color: c.value })}
                  className={`w-6 h-6 rounded border-2 ${form.color === c.value ? 'border-foreground' : 'border-transparent'}`}
                  style={{ backgroundColor: c.value }} title={c.label} />
              ))}
              <input type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })}
                className="w-6 h-6 rounded cursor-pointer border-0 p-0" />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">提醒声音</label>
            <select value={form.sound} onChange={(e) => setForm({ ...form, sound: e.target.value })}
              className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm">
              {sounds.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="checkbox" checked={form.blink} onChange={(e) => setForm({ ...form, blink: e.target.checked })} className="accent-primary" />
            闪烁
          </label>
          <div className="flex items-center gap-2 text-xs">
            预览: <span className={`px-2 py-0.5 rounded text-white text-xs ${form.blink ? 'animate-pulse' : ''}`} style={{ backgroundColor: form.color }}>{form.title || '通知标题'}</span>
          </div>
        </div>
        <Button onClick={handleSend} disabled={sending}>
          <Megaphone className="h-4 w-4" /> {sending ? '发送中...' : '发送通知'}
        </Button>
      </CardContent>
    </Card>
  )
}

// ─── Templates Tab ───

function TemplatesTab() {
  const [templates, setTemplates] = useState<NotificationTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<NotificationTemplate | null>(null)
  const [sounds, setSounds] = useState<SoundPreset[]>([])
  const [testTarget, setTestTarget] = useState<number | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    Promise.all([listNotificationTemplates(), listSounds()])
      .then(([t, s]) => { setTemplates(t); setSounds(s) })
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此模板？')) return
    try { await deleteNotificationTemplate(id); addToast('已删除', 'success'); reload() }
    catch (err: unknown) { addToast(extractError(err, '删除失败'), 'error') }
  }

  const handleCreate = async () => {
    try { await createNotificationTemplate({ template_name: '新模板', category: 'system' }); addToast('已创建', 'success'); reload() }
    catch (err: unknown) { addToast(extractError(err, '创建失败'), 'error') }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  const categoryColors: Record<string, string> = { trade: 'bg-blue-500/20 text-blue-400', risk: 'bg-red-500/20 text-red-400', system: 'bg-gray-500/20 text-gray-400' }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={handleCreate}><Plus className="h-4 w-4" /> 新增模板</Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[850px]">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-3">模板名</th>
                <th className="px-3 py-3">分类</th>
                <th className="px-3 py-3">渠道</th>
                <th className="px-3 py-3">优先级</th>
                <th className="px-3 py-3">跑马灯</th>
                <th className="px-3 py-3">声音</th>
                <th className="px-3 py-3">状态</th>
                <th className="px-3 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {templates.map(t => (
                <tr key={t.id} className="border-b last:border-0 hover:bg-accent/50">
                  <td className="px-3 py-2.5 font-medium">{t.template_name}</td>
                  <td className="px-3 py-2.5"><Badge className={categoryColors[t.category] || ''}>{t.category}</Badge></td>
                  <td className="px-3 py-2.5">
                    <div className="flex gap-1">
                      {t.enable_feishu && <Badge variant="success">飞书</Badge>}
                      {t.enable_email && <Badge variant="default">邮件</Badge>}
                      {t.enable_marquee && <Badge variant="outline">跑马灯</Badge>}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant={t.priority === 1 ? 'destructive' : t.priority === 2 ? 'warning' : 'secondary'}>P{t.priority}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-block w-4 h-4 rounded ${t.marquee_blink ? 'animate-pulse' : ''}`} style={{ backgroundColor: t.marquee_color }} />
                  </td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground">{sounds.find(s => s.key === t.sound_key)?.label || t.sound_key}</td>
                  <td className="px-3 py-2.5">
                    <Badge variant={t.is_enabled ? 'success' : 'secondary'}>{t.is_enabled ? '启用' : '禁用'}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" title="测试" onClick={() => setTestTarget(t.id)}>
                        <Send className="h-3.5 w-3.5 text-primary" />
                      </Button>
                      <Button size="sm" variant="ghost" title="编辑" onClick={() => setEditing(t)}><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button size="sm" variant="ghost" title="删除" onClick={() => handleDelete(t.id)}><Trash2 className="h-3.5 w-3.5 text-negative" /></Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
      {editing && <TemplateEditDialog template={editing} sounds={sounds} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}
      {testTarget && <TemplateTestDialog templateId={testTarget} onClose={() => setTestTarget(null)} />}
    </div>
  )
}

function TemplateTestDialog({ templateId, onClose }: { templateId: number; onClose: () => void }) {
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [sending, setSending] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    listUsers().then((list) => {
      setUsers(list.filter((u: UserItem) => u.feishu_open_id))
    }).finally(() => setLoading(false))
  }, [])

  const handleSend = async () => {
    if (!selected) { addToast('请选择接收用户', 'error'); return }
    setSending(true)
    try {
      const result = await testNotificationTemplate(templateId, selected)
      const channels = result.channels || {}
      const summary = Object.entries(channels).map(([ch, st]) => `${ch}: ${st}`).join(', ')
      const hasError = Object.values(channels).some((s) => s.startsWith('failed') || s.startsWith('error'))
      addToast(`${result.template} — ${summary}`, hasError ? 'error' : 'success')
      onClose()
    } catch (err: unknown) { addToast(extractError(err, '测试失败'), 'error') }
    finally { setSending(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card className="w-[calc(100vw-2rem)] max-w-[400px]">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">选择测试接收人</CardTitle>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <p className="text-sm text-muted-foreground text-center py-4">加载用户...</p>
          ) : users.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">暂无已绑定飞书的用户，请先在用户管理中配置飞书 Open ID</p>
          ) : (
            <div className="space-y-1 max-h-60 overflow-y-auto">
              {users.map((u) => (
                <label key={u.id} className={`flex items-center gap-2 px-3 py-2 rounded cursor-pointer transition-colors ${selected === u.feishu_open_id ? 'bg-primary/10 border border-primary/30' : 'hover:bg-accent/50 border border-transparent'}`}>
                  <input type="radio" name="recipient" value={u.feishu_open_id!} checked={selected === u.feishu_open_id} onChange={() => setSelected(u.feishu_open_id!)} className="accent-primary" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{u.username}</span>
                    {u.display_name && <span className="text-xs text-muted-foreground ml-1">({u.display_name})</span>}
                  </div>
                  <Badge variant="outline" className="text-[10px] shrink-0">{u.feishu_open_id!.slice(0, 12)}...</Badge>
                </label>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" variant="ghost" onClick={onClose}>取消</Button>
            <Button size="sm" onClick={handleSend} disabled={sending || !selected}>
              <Send className="h-3.5 w-3.5" />
              {sending ? '发送中...' : '发送测试'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function TemplateEditDialog({ template, sounds, onClose, onSaved }: {
  template: NotificationTemplate; sounds: SoundPreset[]; onClose: () => void; onSaved: () => void
}) {
  const [form, setForm] = useState({ ...template })
  const [saving, setSaving] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const colorPresets = ['#ef4444', '#f59e0b', '#3b82f6', '#22c55e', '#8b5cf6', '#6b7280']

  const handleSave = async () => {
    setSaving(true)
    try { await updateNotificationTemplate(template.id, form); addToast('模板已更新', 'success'); onSaved() }
    catch (err: unknown) { addToast(extractError(err, '更新失败'), 'error') }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <Card className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm">编辑模板: {template.template_name}</CardTitle>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">模板名</label>
              <Input value={form.template_name} onChange={(e) => setForm({ ...form, template_name: e.target.value })} />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">分类</label>
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm">
                <option value="trade">trade</option>
                <option value="risk">risk</option>
                <option value="system">system</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">标题模板</label>
            <Input value={form.title_template} onChange={(e) => setForm({ ...form, title_template: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">内容模板</label>
            <textarea value={form.content_template} onChange={(e) => setForm({ ...form, content_template: e.target.value })}
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm min-h-[60px]" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">优先级</label>
              <select value={form.priority} onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value) })} className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm">
                <option value={1}>P1 紧急</option>
                <option value={2}>P2 重要</option>
                <option value={3}>P3 普通</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">冷却 (秒)</label>
              <Input type="number" value={form.cooldown_seconds} onChange={(e) => setForm({ ...form, cooldown_seconds: parseInt(e.target.value) || 0 })} />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">提醒声音</label>
              <select value={form.sound_key} onChange={(e) => setForm({ ...form, sound_key: e.target.value })} className="flex h-9 w-full rounded-md border border-input px-3 py-1 text-sm">
                {sounds.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">跑马灯颜色</label>
            <div className="flex gap-1.5 items-center">
              {colorPresets.map(c => (
                <button key={c} onClick={() => setForm({ ...form, marquee_color: c })}
                  className={`w-6 h-6 rounded border-2 ${form.marquee_color === c ? 'border-foreground' : 'border-transparent'}`}
                  style={{ backgroundColor: c }} />
              ))}
              <input type="color" value={form.marquee_color} onChange={(e) => setForm({ ...form, marquee_color: e.target.value })} className="w-6 h-6 rounded cursor-pointer border-0 p-0" />
              <span className="text-xs text-muted-foreground ml-2">{form.marquee_color}</span>
            </div>
          </div>
          <div className="flex gap-4">
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.enable_feishu} onChange={(e) => setForm({ ...form, enable_feishu: e.target.checked })} className="accent-primary" /> 飞书
            </label>
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.enable_email} onChange={(e) => setForm({ ...form, enable_email: e.target.checked })} className="accent-primary" /> 邮件
            </label>
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.enable_marquee} onChange={(e) => setForm({ ...form, enable_marquee: e.target.checked })} className="accent-primary" /> 跑马灯
            </label>
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.marquee_blink} onChange={(e) => setForm({ ...form, marquee_blink: e.target.checked })} className="accent-primary" /> 闪烁
            </label>
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox" checked={form.is_enabled} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} className="accent-primary" /> 启用
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose}>取消</Button>
            <Button onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Logs Tab ───

function LogsTab() {
  const [logs, setLogs] = useState<NotificationLog[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState({ channel: '', status: '', template_name: '' })

  const reload = useCallback(() => {
    setLoading(true)
    const params: Record<string, string | number | undefined> = { page, size: 20 }
    if (filter.channel) params.channel = filter.channel
    if (filter.status) params.status = filter.status
    if (filter.template_name) params.template_name = filter.template_name
    listNotificationLogs(params).then((res) => { setLogs(res.items); setTotal(res.total) }).finally(() => setLoading(false))
  }, [page, filter])
  useEffect(reload, [reload])

  return (
    <div className="space-y-4">
      <div className="flex gap-2 items-center flex-wrap">
        <Input value={filter.template_name} onChange={(e) => { setFilter({ ...filter, template_name: e.target.value }); setPage(1) }}
          placeholder="搜索模板名..." className="w-40" />
        <select value={filter.channel} onChange={(e) => { setFilter({ ...filter, channel: e.target.value }); setPage(1) }}
          className="h-9 rounded-md border border-input px-3 py-1 text-sm">
          <option value="">全部渠道</option>
          <option value="feishu">飞书</option>
          <option value="email">邮件</option>
          <option value="marquee">跑马灯</option>
        </select>
        <select value={filter.status} onChange={(e) => { setFilter({ ...filter, status: e.target.value }); setPage(1) }}
          className="h-9 rounded-md border border-input px-3 py-1 text-sm">
          <option value="">全部状态</option>
          <option value="sent">成功</option>
          <option value="failed">失败</option>
        </select>
      </div>
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-muted-foreground">加载中...</div>
          ) : logs.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">暂无发送记录</div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[650px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-4 py-3">时间</th>
                  <th className="px-4 py-3">模板</th>
                  <th className="px-4 py-3">渠道</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">内容</th>
                </tr>
              </thead>
              <tbody>
                {logs.map(l => (
                  <tr key={l.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">{l.created_at ? new Date(l.created_at).toLocaleString('zh-CN') : '-'}</td>
                    <td className="px-4 py-3">{l.template_name || '-'}</td>
                    <td className="px-4 py-3"><Badge variant="outline">{l.channel}</Badge></td>
                    <td className="px-4 py-3">{l.status === 'sent' ? <CheckCircle className="h-4 w-4 text-positive" /> : <XCircle className="h-4 w-4 text-negative" />}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground truncate max-w-xs">{l.content_preview}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </CardContent>
      </Card>
      {total > 20 && (
        <div className="flex items-center justify-center gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>上一页</Button>
          <span className="text-xs text-muted-foreground">第 {page} 页 / 共 {Math.ceil(total / 20)} 页</span>
          <Button size="sm" variant="outline" disabled={page >= Math.ceil(total / 20)} onClick={() => setPage(p => p + 1)}>下一页</Button>
        </div>
      )}
    </div>
  )
}

// ─── Sounds Tab ───

const AUDIO_CTX_CACHE = { ctx: null as AudioContext | null }
function getAudioCtx() {
  if (!AUDIO_CTX_CACHE.ctx) AUDIO_CTX_CACHE.ctx = new AudioContext()
  return AUDIO_CTX_CACHE.ctx
}

function playSynthSound(key: string) {
  const ctx = getAudioCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.connect(gain)
  gain.connect(ctx.destination)
  gain.gain.value = 0.3
  const now = ctx.currentTime

  switch (key) {
    case 'ding':
      osc.type = 'sine'; osc.frequency.setValueAtTime(880, now); osc.frequency.setValueAtTime(1100, now + 0.1)
      gain.gain.setValueAtTime(0.3, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4)
      osc.start(now); osc.stop(now + 0.4); break
    case 'success':
      osc.type = 'sine'; osc.frequency.setValueAtTime(523, now); osc.frequency.setValueAtTime(659, now + 0.15); osc.frequency.setValueAtTime(784, now + 0.3)
      gain.gain.setValueAtTime(0.3, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.5)
      osc.start(now); osc.stop(now + 0.5); break
    case 'alert':
      osc.type = 'square'; osc.frequency.setValueAtTime(440, now); osc.frequency.setValueAtTime(880, now + 0.15); osc.frequency.setValueAtTime(440, now + 0.3); osc.frequency.setValueAtTime(880, now + 0.45)
      gain.gain.setValueAtTime(0.2, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.6)
      osc.start(now); osc.stop(now + 0.6); break
    case 'error':
      osc.type = 'sawtooth'; osc.frequency.setValueAtTime(200, now); osc.frequency.linearRampToValueAtTime(100, now + 0.5)
      gain.gain.setValueAtTime(0.2, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.5)
      osc.start(now); osc.stop(now + 0.5); break
    case 'chime':
      osc.type = 'sine'; osc.frequency.setValueAtTime(1047, now); osc.frequency.setValueAtTime(1319, now + 0.1); osc.frequency.setValueAtTime(1568, now + 0.2)
      gain.gain.setValueAtTime(0.25, now); gain.gain.exponentialRampToValueAtTime(0.01, now + 0.6)
      osc.start(now); osc.stop(now + 0.6); break
    default: return
  }
}

function SoundsTab() {
  const [sounds, setSounds] = useState<SoundPreset[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { listSounds().then(setSounds).finally(() => setLoading(false)) }, [])

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">提醒声音管理</CardTitle></CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground mb-4">内置 5 种提醒音（Web Audio API 合成，无需音频文件），可在模板管理中绑定到通知模板。</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 lg:grid-cols-3">
          {sounds.map(s => (
            <div key={s.key} className="flex items-center justify-between border rounded-md px-3 py-2">
              <div>
                <span className="text-sm font-medium">{s.label}</span>
                <span className="text-xs text-muted-foreground ml-2">({s.key})</span>
              </div>
              {s.key !== 'none' && (
                <Button size="sm" variant="outline" onClick={() => playSynthSound(s.key)}>
                  <Volume2 className="h-3.5 w-3.5" /> 试听
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
