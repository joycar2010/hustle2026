import { useEffect, useState, useCallback } from 'react'
import {
  getSystemRules, updateSystemRules, broadcastRules, listUserRules,
  type GlobalRulesData,
} from '@/api/admin'
import { extractError } from '@/api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { Save, Send, Users } from 'lucide-react'

type Tab = 'system' | 'users'

export function GlobalRulesPage() {
  const [tab, setTab] = useState<Tab>('system')

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">通用规则</h1>

      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <button onClick={() => setTab('system')}
          className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
            tab === 'system' ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Save className="h-4 w-4" /> 系统默认规则
        </button>
        <button onClick={() => setTab('users')}
          className={`flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
            tab === 'users' ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}>
          <Users className="h-4 w-4" /> 用户规则列表
        </button>
      </div>

      {tab === 'system' && <SystemRulesTab />}
      {tab === 'users' && <UserRulesTab />}
    </div>
  )
}

const RULE_FIELDS: Array<{ key: string; label: string; type: 'decimal' | 'int' | 'bool' }> = [
  { key: 'auto_push_spread', label: '自动推送利差', type: 'decimal' },
  { key: 'remove_spread', label: '撤销利差', type: 'decimal' },
  { key: 'open_spread', label: '开仓利差', type: 'decimal' },
  { key: 'close_spread', label: '平仓利差', type: 'decimal' },
  { key: 'order_amount', label: '订单金额 (USDT)', type: 'decimal' },
  { key: 'close_funding_ratio', label: '平仓资金费率', type: 'decimal' },
  { key: 'repay_funding_ratio', label: '还款资金费率', type: 'decimal' },
  { key: 'borrow_delay_sec', label: '借币延迟 (秒)', type: 'int' },
  { key: 'confirm_delay_sec', label: '确认延迟 (秒)', type: 'int' },
  { key: 'confirm_skip_spread', label: '跳过确认利差', type: 'decimal' },
  { key: 'repay_ban_minutes', label: '还款冷却 (分)', type: 'int' },
  { key: 'interest_filter', label: '利息过滤', type: 'decimal' },
  { key: 'max_loss_per_position', label: '单仓最大亏损 (USDT)', type: 'decimal' },
  { key: 'circuit_breaker_spread_pct', label: '熔断利差阈值 (%)', type: 'decimal' },
  { key: 'circuit_breaker_pause_sec', label: '熔断暂停 (秒)', type: 'int' },
  { key: 'max_daily_interest_rate', label: '最大日利率', type: 'decimal' },
  { key: 'repay_spread', label: '还款利差', type: 'decimal' },
  { key: 'max_positions', label: '最大持仓数', type: 'int' },
  { key: 'auto_start_on_boot', label: '启动时自动运行', type: 'bool' },
  { key: 'futures_liquidation_threshold', label: '合约清算阈值', type: 'decimal' },
]

function SystemRulesTab() {
  const [rules, setRules] = useState<GlobalRulesData | null>(null)
  const [form, setForm] = useState<Record<string, string | boolean>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [broadcasting, setBroadcasting] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = useCallback(() => {
    setLoading(true)
    getSystemRules().then((data) => {
      setRules(data)
      const f: Record<string, string | boolean> = {}
      for (const field of RULE_FIELDS) {
        const val = (data as unknown as Record<string, unknown>)[field.key]
        if (field.type === 'bool') f[field.key] = val === true
        else f[field.key] = val != null ? String(val) : ''
      }
      setForm(f)
    }).finally(() => setLoading(false))
  }, [])

  useEffect(reload, [reload])

  const handleSave = async () => {
    setSaving(true)
    try {
      const body: Record<string, unknown> = {}
      for (const field of RULE_FIELDS) {
        const val = form[field.key]
        if (field.type === 'bool') body[field.key] = val
        else if (field.type === 'int') body[field.key] = val ? parseInt(String(val)) : null
        else body[field.key] = val || null
      }
      await updateSystemRules(body)
      addToast('规则已保存', 'success')
      reload()
    } catch (err: unknown) { addToast(extractError(err, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  const handleBroadcast = async () => {
    if (!confirm('确认将系统默认规则分发给所有用户？此操作将覆盖所有用户的规则设置。')) return
    setBroadcasting(true)
    try {
      const res = await broadcastRules()
      addToast(`规则已分发给 ${res.updated} 个用户`, 'success')
    } catch (err: unknown) { addToast(extractError(err, '分发失败'), 'error') }
    finally { setBroadcasting(false) }
  }

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-sm">
            <span>系统默认规则 {rules?.updated_at && <span className="text-xs text-muted-foreground font-normal ml-2">更新于 {rules.updated_at.slice(0, 19)}</span>}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={handleBroadcast} disabled={broadcasting}>
                <Send className="h-4 w-4" /> {broadcasting ? '分发中...' : '分发给所有用户'}
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                <Save className="h-4 w-4" /> {saving ? '保存中...' : '保存'}
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {RULE_FIELDS.map(field => (
              <div key={field.key} className="space-y-1">
                <label className="text-xs text-muted-foreground">{field.label}</label>
                {field.type === 'bool' ? (
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, [field.key]: !form[field.key] })}
                    className={`flex h-9 w-full items-center justify-center rounded-md border text-sm ${
                      form[field.key] ? 'bg-primary/20 border-primary text-primary' : 'bg-transparent border-input text-muted-foreground'
                    }`}
                  >
                    {form[field.key] ? '开启' : '关闭'}
                  </button>
                ) : (
                  <Input
                    type="number"
                    step={field.type === 'decimal' ? '0.0001' : '1'}
                    value={String(form[field.key] || '')}
                    onChange={(e) => setForm({ ...form, [field.key]: e.target.value })}
                  />
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function UserRulesTab() {
  const [rules, setRules] = useState<GlobalRulesData[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listUserRules().then(setRules).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-3 whitespace-nowrap">用户</th>
                <th className="px-3 py-3 text-right">开仓利差</th>
                <th className="px-3 py-3 text-right">平仓利差</th>
                <th className="px-3 py-3 text-right">订单金额</th>
                <th className="px-3 py-3 text-right">最大持仓</th>
                <th className="px-3 py-3 text-right">利息过滤</th>
                <th className="px-3 py-3">自动启动</th>
                <th className="px-3 py-3 text-right">更新时间</th>
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">暂无数据</td></tr>
              ) : (
                rules.map(r => (
                  <tr key={r.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 font-medium">{r.username}</td>
                    <td className="px-3 py-3 text-right font-mono text-xs">{r.open_spread}</td>
                    <td className="px-3 py-3 text-right font-mono text-xs">{r.close_spread}</td>
                    <td className="px-3 py-3 text-right">{r.order_amount}</td>
                    <td className="px-3 py-3 text-right">{r.max_positions}</td>
                    <td className="px-3 py-3 text-right font-mono text-xs">{r.interest_filter}</td>
                    <td className="px-3 py-3">
                      <Badge variant={r.auto_start_on_boot ? 'success' : 'secondary'}>
                        {r.auto_start_on_boot ? 'ON' : 'OFF'}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-muted-foreground">{r.updated_at?.slice(0, 19)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
