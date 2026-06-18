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
import { Save, Send, Users, Server } from 'lucide-react'

type Tab = 'system' | 'backend' | 'users'

export function GlobalRulesPage() {
  const [tab, setTab] = useState<Tab>('system')

  const tabCls = (active: boolean) =>
    `flex items-center gap-1.5 whitespace-nowrap shrink-0 border-b-2 px-4 py-2.5 text-sm transition-colors ${
      active ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
    }`

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">通用规则</h1>

      <div className="flex gap-1 border-b overflow-x-auto scrollbar-hide">
        <button onClick={() => setTab('system')} className={tabCls(tab === 'system')}>
          <Save className="h-4 w-4" /> 系统用户通用规则
        </button>
        <button onClick={() => setTab('backend')} className={tabCls(tab === 'backend')}>
          <Server className="h-4 w-4" /> 系统基础规则
        </button>
        <button onClick={() => setTab('users')} className={tabCls(tab === 'users')}>
          <Users className="h-4 w-4" /> 用户规则列表
        </button>
      </div>

      {tab === 'system' && <RulesTab fields={RULE_FIELDS} title="系统用户通用规则" showBroadcast />}
      {tab === 'backend' && <BackendRulesTab />}
      {tab === 'users' && <UserRulesTab />}
    </div>
  )
}

type FieldType = 'decimal' | 'int' | 'bool' | 'string'
type RuleField = { key: string; label: string; type: FieldType }

const RULE_FIELDS: RuleField[] = [
  { key: 'auto_push_spread', label: '自动推送利差', type: 'decimal' },
  { key: 'remove_spread', label: '撤销利差', type: 'decimal' },
  { key: 'borrow_spread', label: '挂单点差', type: 'decimal' },
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
  { key: 'repay_spread', label: '还款利差', type: 'decimal' },
  { key: 'max_positions', label: '最大持仓数', type: 'int' },
  { key: 'auto_start_on_boot', label: '启动时自动运行', type: 'bool' },
  // 已摘除 4 个零消费死字段:circuit_breaker_spread_pct/circuit_breaker_pause_sec(引擎未接)、
  // max_daily_interest_rate(实际限利息用 interest_filter)、futures_liquidation_threshold(消费者 ensure_margin_balance 已不在实盘链,实盘走 margin_balancer)
]

function RulesTab({ fields, title, showBroadcast = false }: { fields: RuleField[]; title: string; showBroadcast?: boolean }) {
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
      for (const field of fields) {
        const val = (data as unknown as Record<string, unknown>)[field.key]
        if (field.type === 'bool') f[field.key] = val === true
        else f[field.key] = val != null ? String(val) : ''
      }
      setForm(f)
    }).finally(() => setLoading(false))
  }, [fields])

  useEffect(reload, [reload])

  const handleSave = async () => {
    setSaving(true)
    try {
      const body: Record<string, unknown> = {}
      for (const field of fields) {
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
    if (!confirm('确认将系统用户通用规则分发给所有用户？此操作将覆盖所有用户的规则设置。')) return
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
            <span>{title} {rules?.updated_at && <span className="text-xs text-muted-foreground font-normal ml-2">更新于 {rules.updated_at.slice(0, 19)}</span>}</span>
            <div className="flex gap-2">
              {showBroadcast && (
                <Button size="sm" variant="outline" onClick={handleBroadcast} disabled={broadcasting}>
                  <Send className="h-4 w-4" /> {broadcasting ? '分发中...' : '分发给所有用户'}
                </Button>
              )}
              <Button size="sm" onClick={handleSave} disabled={saving}>
                <Save className="h-4 w-4" /> {saving ? '保存中...' : '保存'}
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 lg:grid-cols-4">
            {fields.map(field => (
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
                ) : field.type === 'string' ? (
                  <Input
                    type="text"
                    value={String(form[field.key] || '')}
                    onChange={(e) => setForm({ ...form, [field.key]: e.target.value })}
                  />
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

const pill = (on: boolean, neg = false) =>
  `px-2 py-0.5 rounded text-[12px] whitespace-nowrap ${on ? (neg ? 'bg-destructive/20 text-destructive' : 'bg-primary/20 text-primary') : 'bg-muted text-muted-foreground'}`

// 系统基础规则:复刻 coin /rules「黄框」密集行内布局(对所有用户全局生效;写 user_id IS NULL 行)
function BackendRulesTab() {
  const [form, setForm] = useState<Record<string, string | boolean>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  const STR = ['follow_type', 'tier_ratios', 'borrow_mode']
  const BOOL = ['hedge_via_master', 'borrow_via_otoco', 'block_risky_open']
  const INT = ['otoco_legs', 'multi_max_accounts_per_symbol', 'filter_duration_ms', 'removed_cooldown_minutes', 'spread_stale_sec']
  const NUM = ['slippage_pct', 'stabilize_sec', 'borrow_rate_per_sec', 'max_spread_pct', 'min_volume_24h',
    'min_volume_24h_futures', 'min_borrow_usdt', 'collateral_ratio', 'open_spread_buffer', 'taker_fee_spot', 'taker_fee_futures']

  const reload = useCallback(() => {
    setLoading(true)
    getSystemRules().then((d) => {
      const rec = d as unknown as Record<string, unknown>
      const f: Record<string, string | boolean> = {}
      for (const k of [...STR, ...INT, ...NUM]) f[k] = rec[k] != null ? String(rec[k]) : ''
      for (const k of BOOL) f[k] = rec[k] === true
      setForm(f)
      setUpdatedAt(d.updated_at)
    }).finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(reload, [reload])

  const save = async () => {
    setSaving(true)
    try {
      const b: Record<string, unknown> = {}
      for (const k of STR) b[k] = form[k] || null
      for (const k of BOOL) b[k] = form[k] === true
      for (const k of INT) b[k] = form[k] ? parseInt(String(form[k])) : null
      for (const k of NUM) b[k] = form[k] ? String(form[k]) : null
      await updateSystemRules(b)
      addToast('系统基础规则已保存', 'success')
      reload()
    } catch (e) { addToast(extractError(e, '保存失败'), 'error') }
    finally { setSaving(false) }
  }

  const setV = (k: string, v: string | boolean) => setForm((p) => ({ ...p, [k]: v }))
  const val = (k: string) => String(form[k] ?? '')
  const feePct = (k: string) => { const n = parseFloat(String(form[k])); return isNaN(n) ? '' : String(+(n * 100).toFixed(4)) }
  const setFee = (k: string, v: string) => setV(k, String((parseFloat(v) || 0) / 100))

  const inp = 'w-16 bg-transparent border-b border-input text-center text-foreground text-[12px] focus:outline-none focus:border-primary py-0.5'
  const lbl = 'inline-flex items-center gap-1 text-muted-foreground'
  const desc = 'text-muted-foreground/60 text-[11px]'
  const sel = 'bg-background border border-input rounded px-1.5 py-0.5 text-[12px] text-foreground'

  if (loading) return <div className="text-muted-foreground py-8 text-center">加载中...</div>

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm">
          <span>系统基础规则（对所有用户全局生效）{updatedAt && <span className="text-xs text-muted-foreground font-normal ml-2">更新于 {updatedAt.slice(0, 19)}</span>}</span>
          <Button size="sm" onClick={save} disabled={saving}><Save className="h-4 w-4" /> {saving ? '保存中...' : '保存'}</Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-[12px]">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="text-muted-foreground/70">下单质量(高级)</span>
          <span className={lbl}>跟单方式
            <select value={String(form.follow_type || 'market')} onChange={(e) => setV('follow_type', e.target.value)} className={sel}>
              <option value="market">市价</option><option value="limit">限价</option>
            </select></span>
          <span className={lbl}>滑点 <input className={inp} value={val('slippage_pct')} onChange={(e) => setV('slippage_pct', e.target.value)} /> %</span>
          <span className={lbl}>现货成交后等待 <input className={inp} value={val('stabilize_sec')} onChange={(e) => setV('stabilize_sec', e.target.value)} /> 秒</span>
          <span className={lbl}>分层建仓 <input className="w-28 bg-transparent border-b border-input text-center text-foreground text-[12px] focus:outline-none focus:border-primary py-0.5" value={val('tier_ratios')} onChange={(e) => setV('tier_ratios', e.target.value)} /></span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-muted-foreground/70">限流</span>
          <span className={lbl}>每账户借币速率 <input className={inp} value={val('borrow_rate_per_sec')} onChange={(e) => setV('borrow_rate_per_sec', e.target.value)} /> 次/秒</span>
          <span className={desc}>单 UID 硬顶 2/秒;多账户聚合 = 本值×账户数</span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-muted-foreground/70">借币方式</span>
          <select
            value={String(form.borrow_mode || (form.borrow_via_otoco === true ? 'otoco' : 'repay'))}
            onChange={(e) => {
              const m = e.target.value
              setV('borrow_mode', m)
              setV('borrow_via_otoco', m === 'otoco')   // 双写旧 bool,灰度回退安全
            }}
            className={sel}
          >
            <option value="repay">borrow-repay 直接借</option>
            <option value="otoco">IOC OTOCO 挂单借币</option>
            <option value="single">单腿 MARGIN_BUY(最快,省额度)</option>
            <option value="multi">多账户并联(突破单UID)</option>
          </select>
          <span className={lbl}>撤单腿数
            <select value={String(form.otoco_legs ?? '2')} onChange={(e) => setV('otoco_legs', e.target.value)} className={sel}>
              <option value="1">1 单 (单腿MARGIN_BUY)</option>
              <option value="2">2 单 (OTO)</option>
              <option value="3">3 单 (OTOCO)</option>
            </select></span>
          <span className={lbl}>并联上限
            <input
              type="number" min={1} max={50}
              value={String(form.multi_max_accounts_per_symbol ?? '')}
              onChange={(e) => setV('multi_max_accounts_per_symbol', e.target.value)}
              disabled={String(form.borrow_mode) !== 'multi'}
              className={inp + (String(form.borrow_mode) !== 'multi' ? ' opacity-40' : '')}
              title="多账户并联: 同一币最多几个子账户同时并联借(突破单UID order-count瓶颈)"
            /></span>
          <span className={desc}>单腿=order-count仅1笔(~10/s);并联=N倍UID预算</span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-muted-foreground/70">对冲腿</span>
          <button type="button" onClick={() => setV('hedge_via_master', !(form.hedge_via_master === true))} className={pill(form.hedge_via_master === true)}>{form.hedge_via_master === true ? '主账户合约对冲' : '子账户合约对冲'}</button>
          <span className={lbl}>点差护栏 <input className={inp} value={val('max_spread_pct')} onChange={(e) => setV('max_spread_pct', e.target.value)} /> %</span>
          <span className={lbl}>现货量护栏 <input className={inp} value={val('min_volume_24h')} onChange={(e) => setV('min_volume_24h', e.target.value)} /> U</span>
          <span className={lbl}>合约量护栏 <input className={inp} value={val('min_volume_24h_futures')} onChange={(e) => setV('min_volume_24h_futures', e.target.value)} /> U</span>
          <button type="button" onClick={() => setV('block_risky_open', !(form.block_risky_open === true))} className={pill(form.block_risky_open === true, true)}>{form.block_risky_open === true ? '风险币禁开仓' : '风险币仅告警'}</button>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-muted-foreground/70">信号护栏</span>
          <span className={lbl}>点差防抖 <input className={inp} value={val('filter_duration_ms')} onChange={(e) => setV('filter_duration_ms', e.target.value)} /> ms</span>
          <span className={lbl}>借币下限 <input className={inp} value={val('min_borrow_usdt')} onChange={(e) => setV('min_borrow_usdt', e.target.value)} /> U</span>
          <span className={lbl}>抵押率 <input className={inp} value={val('collateral_ratio')} onChange={(e) => setV('collateral_ratio', e.target.value)} /></span>
          <span className={lbl}>移除冷却 <input className={inp} value={val('removed_cooldown_minutes')} onChange={(e) => setV('removed_cooldown_minutes', e.target.value)} /> 分</span>
          <span className={lbl}>开仓缓冲 <input className={inp} value={val('open_spread_buffer')} onChange={(e) => setV('open_spread_buffer', e.target.value)} /> %</span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-muted-foreground/70">利差监控</span>
          <span className={lbl}>新鲜阈值 <input className={inp} value={val('spread_stale_sec')} onChange={(e) => setV('spread_stale_sec', e.target.value)} /> 秒</span>
          <span className={desc}>/spreads 利差监控:某币 ts 落后全表最新值超此秒数即视为死币/冻结,不显示(默认 300)</span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-muted-foreground/70">手续费(PnL口径)</span>
          <span className={lbl}>现货吃单 <input className={inp} value={feePct('taker_fee_spot')} onChange={(e) => setFee('taker_fee_spot', e.target.value)} /> %</span>
          <span className={lbl}>合约吃单 <input className={inp} value={feePct('taker_fee_futures')} onChange={(e) => setFee('taker_fee_futures', e.target.value)} /> %</span>
          <span className={desc}>仅用于盈亏/报表口径,不影响开仓决策;开 BNB 抵扣后实际更低</span>
        </div>
        <div className={desc}>限价:合约腿用可成交限价(挂价≥卖一×(1+滑点))封顶滑点,超时未成交自动市价补齐——永不留敞口。分层格式「偏移%:数量%」如 0.5:30,0.8:30,1.2:40。</div>
      </CardContent>
    </Card>
  )
}

// 用户规则列表审计列 = 与「系统用户通用规则」同一组 per-user GlobalRules 字段(17 项);只读,列宽按数据自适应
const USER_COLS: { key: string; label: string; title: string; kind: 'num' | 'int' | 'bool' }[] = [
  { key: 'auto_push_spread', label: '推送利差', title: 'auto_push_spread 自动推送利差', kind: 'num' },
  { key: 'remove_spread', label: '移除利差', title: 'remove_spread 点差不足移除', kind: 'num' },
  { key: 'borrow_spread', label: '挂单点差', title: 'borrow_spread 挂单点差(借币触发阈,≤开仓)', kind: 'num' },
  { key: 'open_spread', label: '开仓利差', title: 'open_spread 开仓利差', kind: 'num' },
  { key: 'close_spread', label: '平仓利差', title: 'close_spread 平仓利差', kind: 'num' },
  { key: 'order_amount', label: '订单金额', title: 'order_amount 单笔下单额(USDT)', kind: 'num' },
  { key: 'close_funding_ratio', label: '平资费', title: 'close_funding_ratio 平仓资费倍率', kind: 'num' },
  { key: 'repay_funding_ratio', label: '还资费', title: 'repay_funding_ratio 还币资费倍率', kind: 'num' },
  { key: 'borrow_delay_sec', label: '借币延迟', title: 'borrow_delay_sec 借币延迟开仓(秒)', kind: 'int' },
  { key: 'confirm_delay_sec', label: '确认延迟', title: 'confirm_delay_sec 推送二次确认(秒)', kind: 'int' },
  { key: 'confirm_skip_spread', label: '跳过确认', title: 'confirm_skip_spread 点差≥此直推(跳二次确认)', kind: 'num' },
  { key: 'repay_ban_minutes', label: '还款冷却', title: 'repay_ban_minutes 首次借币后禁还(分)', kind: 'int' },
  { key: 'interest_filter', label: '利息过滤', title: 'interest_filter 日利息拦截(%)', kind: 'num' },
  { key: 'max_loss_per_position', label: '单仓止损', title: 'max_loss_per_position 单仓最大亏损(USDT)', kind: 'num' },
  { key: 'repay_spread', label: '还币利差', title: 'repay_spread 自动还币开仓点差', kind: 'num' },
  { key: 'max_positions', label: '最大持仓', title: 'max_positions 最大持仓数', kind: 'int' },
  { key: 'auto_start_on_boot', label: '自动启动', title: 'auto_start_on_boot 启动时自动运行', kind: 'bool' },
]

// 数值去尾零(窄列友好);null/空 → '-'
const auditNum = (v: unknown): string => {
  if (v == null || v === '') return '-'
  const s = String(v)
  return s.includes('.') ? (s.replace(/\.?0+$/, '') || '0') : s
}
const auditInt = (v: unknown): string => (v == null || v === '' ? '-' : String(v))

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
        {/* 列宽按数据自适应:表用 auto 布局 + 单元格 whitespace-nowrap,各列贴合内容;超出容器横向滚动,用户列 sticky 固定 */}
        <div className="overflow-x-auto">
          <table className="text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-2.5 whitespace-nowrap sticky left-0 bg-card z-10">用户</th>
                {USER_COLS.map(c => (
                  <th key={c.key} title={c.title}
                    className={`px-2.5 py-2.5 whitespace-nowrap ${c.kind === 'bool' ? 'text-center' : 'text-right'}`}>
                    {c.label}
                  </th>
                ))}
                <th className="px-3 py-2.5 text-right whitespace-nowrap">更新时间</th>
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 ? (
                <tr><td colSpan={USER_COLS.length + 2} className="px-4 py-8 text-center text-muted-foreground">暂无数据</td></tr>
              ) : (
                rules.map(r => {
                  const rec = r as unknown as Record<string, unknown>
                  return (
                    <tr key={r.id} className="border-b last:border-0 hover:bg-accent/50">
                      <td className="px-3 py-2.5 font-medium whitespace-nowrap sticky left-0 bg-card">{r.username}</td>
                      {USER_COLS.map(c => (
                        c.kind === 'bool' ? (
                          <td key={c.key} className="px-2.5 py-2.5 text-center whitespace-nowrap">
                            <Badge variant={rec[c.key] ? 'success' : 'secondary'}>{rec[c.key] ? 'ON' : 'OFF'}</Badge>
                          </td>
                        ) : (
                          <td key={c.key} className="px-2.5 py-2.5 text-right font-mono text-xs whitespace-nowrap">
                            {c.kind === 'int' ? auditInt(rec[c.key]) : auditNum(rec[c.key])}
                          </td>
                        )
                      ))}
                      <td className="px-3 py-2.5 text-right text-xs text-muted-foreground whitespace-nowrap">{r.updated_at?.slice(0, 19)}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
