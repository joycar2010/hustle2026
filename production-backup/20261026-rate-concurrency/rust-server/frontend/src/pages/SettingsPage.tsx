import { useEffect, useState } from 'react'
import { getProfile, updateProfile, feishuLookup, type UserProfile } from '@/api/auth'
import { useToastStore } from '@/components/ui/toast'
import { extractError } from '@/api/client'
import { cn } from '@/lib/utils'

export function SettingsPage({ embedded }: { onClose?: () => void; embedded?: boolean } = {}) {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [form, setForm] = useState({
    email: '',
    display_name: '',
    feishu_phone: '',
    feishu_open_id: '',
    feishu_union_id: '',
    password: '',
  })
  const [saving, setSaving] = useState(false)
  const [lookingUp, setLookingUp] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    getProfile().then((p) => {
      setProfile(p)
      setForm({
        email: p.email || '',
        display_name: p.display_name || '',
        feishu_phone: p.feishu_phone || '',
        feishu_open_id: p.feishu_open_id || '',
        feishu_union_id: p.feishu_union_id || '',
        password: '',
      })
    }).catch(() => addToast('加载用户信息失败', 'error'))
  }, [addToast])

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload: Record<string, string> = {}
      if (form.email !== (profile?.email || '')) payload.email = form.email
      if (form.display_name !== (profile?.display_name || '')) payload.display_name = form.display_name
      if (form.feishu_phone !== (profile?.feishu_phone || '')) payload.feishu_phone = form.feishu_phone
      if (form.feishu_open_id !== (profile?.feishu_open_id || '')) payload.feishu_open_id = form.feishu_open_id
      if (form.feishu_union_id !== (profile?.feishu_union_id || '')) payload.feishu_union_id = form.feishu_union_id
      if (form.password) payload.password = form.password

      if (Object.keys(payload).length === 0) {
        addToast('没有修改', 'info')
        setSaving(false)
        return
      }
      await updateProfile(payload)
      addToast('保存成功', 'success')
      setForm((f) => ({ ...f, password: '' }))
      const updated = await getProfile()
      setProfile(updated)
    } catch (err: unknown) {
      addToast(extractError(err, '保存失败'), 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleFeishuLookup = async () => {
    const phone = form.feishu_phone.trim()
    if (!phone) {
      addToast('请先输入飞书手机号', 'error')
      return
    }
    setLookingUp(true)
    try {
      const result = await feishuLookup(phone)
      setForm((f) => ({
        ...f,
        feishu_open_id: result.open_id || f.feishu_open_id,
        feishu_union_id: result.union_id || f.feishu_union_id,
      }))
      addToast('飞书ID获取成功', 'success')
    } catch (err: unknown) {
      addToast(extractError(err, '查询失败'), 'error')
    } finally {
      setLookingUp(false)
    }
  }

  if (!profile) {
    return <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">加载中...</div>
  }

  const inputCls = 'w-full bg-[#1a1a22] border border-border rounded px-2.5 py-1.5 text-[12px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-colors'
  const labelCls = 'block text-[11px] text-muted-foreground mb-1'
  const readonlyCls = 'w-full bg-[#111118] border border-border/50 rounded px-2.5 py-1.5 text-[12px] text-muted-foreground cursor-not-allowed'

  return (
    <div className={embedded ? 'flex items-start justify-center p-3' : 'flex items-start justify-center py-8 px-4'}>
      <div className="w-full max-w-lg bg-[#111118] border border-border rounded-lg overflow-hidden">
        {/* Header — 嵌入模态时隐藏左侧"用户设置"标题(模态栏已展示),仅保留右侧角色/上次登录信息 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-[#0d0d14]">
          {embedded ? <span /> : <h2 className="text-sm font-medium text-foreground">用户设置</h2>}
          <span className="text-[10px] text-muted-foreground">
            {profile.role} · 上次登录 {profile.last_login_at ? new Date(profile.last_login_at).toLocaleString('zh-CN') : '-'}
          </span>
        </div>

        <form autoComplete="off" onSubmit={(e) => e.preventDefault()} className="p-4 space-y-4">
          {/* Hidden fields to absorb browser autofill */}
          <input type="text" name="fake-user" autoComplete="username" style={{ display: 'none' }} tabIndex={-1} />
          <input type="password" name="fake-pass" autoComplete="current-password" style={{ display: 'none' }} tabIndex={-1} />
          {/* Basic info */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>用户名</label>
              <input value={profile.username} disabled className={readonlyCls} />
            </div>
            <div>
              <label className={labelCls}>显示名</label>
              <input
                value={form.display_name}
                onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                placeholder="显示名称"
                className={inputCls}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>邮箱</label>
              <input
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="email@example.com"
                autoComplete="off"
                name="profile-email"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls}>修改密码</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                placeholder="留空则不修改"
                autoComplete="new-password"
                name="profile-new-pw"
                className={inputCls}
              />
            </div>
          </div>

          {/* Divider */}
          <div className="border-t border-border pt-3">
            <span className="text-[11px] text-primary font-medium">飞书配置</span>
          </div>

          {/* Feishu phone + lookup button */}
          <div>
            <label className={labelCls}>飞书手机号</label>
            <div className="flex gap-2">
              <input
                value={form.feishu_phone}
                onChange={(e) => setForm((f) => ({ ...f, feishu_phone: e.target.value }))}
                placeholder="13800138000"
                className={cn(inputCls, 'flex-1')}
              />
              <button
                onClick={handleFeishuLookup}
                disabled={lookingUp || !form.feishu_phone.trim()}
                className={cn(
                  'px-3 py-1.5 rounded text-[11px] font-medium whitespace-nowrap transition-colors shrink-0',
                  'bg-primary/20 text-primary hover:bg-primary/30',
                  (lookingUp || !form.feishu_phone.trim()) && 'opacity-40 cursor-not-allowed',
                )}
              >
                {lookingUp ? '查询中...' : '获取飞书ID'}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>飞书 Open ID</label>
              <input
                value={form.feishu_open_id}
                onChange={(e) => setForm((f) => ({ ...f, feishu_open_id: e.target.value }))}
                placeholder="ou_xxxxxxxxxx"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls}>飞书 Union ID</label>
              <input
                value={form.feishu_union_id}
                onChange={(e) => setForm((f) => ({ ...f, feishu_union_id: e.target.value }))}
                placeholder="on_xxxxxxxxxx"
                className={inputCls}
              />
            </div>
          </div>

          {/* Read-only info */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>角色</label>
              <input value={profile.role} disabled className={readonlyCls} />
            </div>
            <div>
              <label className={labelCls}>最大子账户数</label>
              <input value={profile.max_sub_accounts} disabled className={readonlyCls} />
            </div>
          </div>

          {/* Save */}
          <div className="flex justify-end pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className={cn(
                'px-6 py-2 rounded text-[12px] font-medium transition-colors',
                'bg-primary text-primary-foreground hover:bg-primary/90',
                saving && 'opacity-50 cursor-not-allowed',
              )}
            >
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
