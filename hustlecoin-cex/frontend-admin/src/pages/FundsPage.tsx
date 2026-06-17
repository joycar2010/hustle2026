import { useEffect, useState, useCallback, Fragment } from 'react'
import {
  getAdminFundsOverview, getAdminFundsCurve, getAdminPnlAttribution,
  type AdminFundsOverview, type AdminFundsUser, type AdminFundsCurvePoint, type AdminPnlAttrRow,
} from '@/api/admin'
import { cn, formatNumber } from '@/lib/utils'

const REFRESH_MS = 15000  // balance:latest TTL 30s,15s 轮询保证不陈旧

// 内联 SVG 资金净值折线(数据稀疏,零依赖)
function EquityCurve({ points }: { points: AdminFundsCurvePoint[] }) {
  const W = 900, H = 180, PAD = 36
  if (points.length === 0) {
    return <div className="h-[180px] flex items-center justify-center text-muted-foreground text-xs">暂无快照数据(引擎每 10 分钟落一次,稍后即有曲线)</div>
  }
  const xs = points.map((_, i) => i)
  const ys = points.map((p) => p.equity)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const spanY = maxY - minY || Math.max(1, Math.abs(maxY) * 0.02)
  const lo = minY - spanY * 0.1, hi = maxY + spanY * 0.1
  const px = (i: number) => points.length === 1 ? W / 2 : PAD + (i / (points.length - 1)) * (W - 2 * PAD)
  const py = (v: number) => H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD)
  const line = xs.map((i) => `${px(i)},${py(ys[i])}`).join(' ')
  const last = points[points.length - 1]
  const first = points[0]
  const delta = last.equity - first.equity
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[180px]" preserveAspectRatio="none">
      {/* y grid: min/max */}
      <line x1={PAD} y1={py(hi)} x2={W - PAD} y2={py(hi)} stroke="currentColor" className="text-border/40" strokeWidth="1" />
      <line x1={PAD} y1={py(lo)} x2={W - PAD} y2={py(lo)} stroke="currentColor" className="text-border/40" strokeWidth="1" />
      <text x={2} y={py(hi) + 4} className="fill-muted-foreground" fontSize="10">{formatNumber(maxY)}</text>
      <text x={2} y={py(lo) + 4} className="fill-muted-foreground" fontSize="10">{formatNumber(minY)}</text>
      {points.length > 1 && (
        <polyline points={line} fill="none" stroke="currentColor" className={delta >= 0 ? 'text-positive' : 'text-negative'} strokeWidth="1.5" />
      )}
      {points.map((p, i) => (
        <circle key={i} cx={px(i)} cy={py(p.equity)} r={points.length === 1 ? 3 : 1.8} className={delta >= 0 ? 'fill-positive' : 'fill-negative'}>
          <title>{p.ts.slice(0, 19)} · 净值 {formatNumber(p.equity)}</title>
        </circle>
      ))}
    </svg>
  )
}

function StatCard({ label, value, hint, accent }: { label: string; value: string; hint?: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('text-lg font-bold tabular-nums mt-0.5', accent)}>{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground/60 mt-0.5">{hint}</div>}
    </div>
  )
}

function pnlColor(n: number | null): string {
  if (n == null) return 'text-muted-foreground'
  if (n > 0) return 'text-positive'
  if (n < 0) return 'text-negative'
  return 'text-foreground'
}

function marginColor(lv: number | null): string {
  if (lv == null) return 'text-muted-foreground/50'
  if (lv < 1.3) return 'text-negative font-medium'
  if (lv < 1.8) return 'text-amber-400'
  return 'text-positive'
}

export function FundsPage() {
  const [data, setData] = useState<AdminFundsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string>('')
  const [curveUser, setCurveUser] = useState<string>('')   // '' = 全平台
  const [curveDays, setCurveDays] = useState<number>(7)
  const [curve, setCurve] = useState<AdminFundsCurvePoint[]>([])
  const [attrBy, setAttrBy] = useState<'user' | 'symbol' | 'day'>('day')
  const [attrDays, setAttrDays] = useState<number>(30)
  const [attrRows, setAttrRows] = useState<AdminPnlAttrRow[]>([])

  const fetchData = useCallback(async () => {
    try {
      const d = await getAdminFundsOverview()
      setData(d)
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN'))
    } catch { /* keep last */ }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, REFRESH_MS)
    return () => clearInterval(t)
  }, [fetchData])

  const fetchCurve = useCallback(async () => {
    try {
      const params: Record<string, string | number> = { days: curveDays }
      if (curveUser) params.user_id = curveUser
      const d = await getAdminFundsCurve(params)
      setCurve(d.points)
    } catch { setCurve([]) }
  }, [curveUser, curveDays])

  useEffect(() => {
    fetchCurve()
    const t = setInterval(fetchCurve, 60000)  // 曲线 1min 刷新即可(快照 10min 才新增)
    return () => clearInterval(t)
  }, [fetchCurve])

  const fetchAttr = useCallback(async () => {
    try {
      const d = await getAdminPnlAttribution({ group_by: attrBy, days: attrDays })
      setAttrRows(d.rows)
    } catch { setAttrRows([]) }
  }, [attrBy, attrDays])

  useEffect(() => { fetchAttr() }, [fetchAttr])

  const t = data?.totals

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 px-1">
        <h1 className="text-xl font-bold">用户资金统计</h1>
        <span className="text-[11px] text-muted-foreground ml-auto">
          {updatedAt && `更新 ${updatedAt}`} · 每 {REFRESH_MS / 1000}s 刷新 · 数据源 Redis 实时快照
        </span>
      </div>

      {/* Platform totals */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
        <StatCard label="全平台净值" value={t ? `${formatNumber(t.equity)} U` : '-'} accent="text-primary" hint={t ? `${t.users_with_data}/${t.users_total} 用户有数据` : undefined} />
        <StatCard label="总可用" value={t ? `${formatNumber(t.available)} U` : '-'} />
        <StatCard label="总已借(USDT)" value={t ? `${formatNumber(t.borrowed)} U` : '-'} />
        <StatCard label="总未实现盈亏" value={t ? `${formatNumber(t.unrealized_pnl)} U` : '-'} accent={pnlColor(t?.unrealized_pnl ?? 0)} />
        <StatCard label="部署名义额" value={t ? `${formatNumber(t.deployed_notional)} U` : '-'} hint="开仓名义,非净值" />
        <StatCard label="有数据用户" value={t ? `${t.users_with_data} / ${t.users_total}` : '-'} />
      </div>

      {/* Equity curve */}
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[12px] font-semibold text-foreground">资金净值曲线</span>
          <select
            value={curveUser}
            onChange={(e) => setCurveUser(e.target.value)}
            className="bg-[#1a1a22] border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground focus:outline-none focus:border-primary"
          >
            <option value="">全平台</option>
            {data?.users.map((u) => <option key={u.user_id} value={u.user_id}>{u.username}</option>)}
          </select>
          <div className="flex rounded border border-border overflow-hidden">
            {[7, 30, 90].map((d) => (
              <button key={d} onClick={() => setCurveDays(d)}
                className={cn('px-2 py-0.5 text-[11px] border-r border-border last:border-0', curveDays === d ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-accent/50')}>
                {d}天
              </button>
            ))}
          </div>
          <span className="text-[10px] text-muted-foreground ml-auto">{curve.length} 个快照点</span>
        </div>
        <div className="text-foreground"><EquityCurve points={curve} /></div>
      </div>

      {/* Per-user table */}
      <div className="rounded-lg border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-[11px] border-collapse">
            <thead>
              <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                <th className="px-3 py-2 text-left font-medium">用户</th>
                <th className="px-3 py-2 text-right font-medium">净值</th>
                <th className="px-3 py-2 text-right font-medium">可用</th>
                <th className="px-3 py-2 text-right font-medium" title="USDT 已借(币借入折算见净值)">已借</th>
                <th className="px-3 py-2 text-right font-medium">未实现盈亏</th>
                <th className="px-3 py-2 text-right font-medium" title="最差子账户保证金水平,<1.3 红 / <1.8 黄">最低保证金</th>
                <th className="px-3 py-2 text-right font-medium">账户数</th>
                <th className="px-3 py-2 text-right font-medium" title="开仓名义额(open_usdt_amount),非账户净值">部署名义额</th>
                <th className="px-3 py-2 text-right font-medium">持仓</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : !data || data.users.length === 0 ? (
                <tr><td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">暂无用户</td></tr>
              ) : data.users.map((u: AdminFundsUser) => {
                const isExp = expanded === u.user_id
                return (
                  <Fragment key={u.user_id}>
                  <tr
                    onClick={() => setExpanded(isExp ? null : u.user_id)}
                    className="border-b border-border/30 hover:bg-[#1a1a22]/60 cursor-pointer"
                  >
                    <td className="px-3 py-1.5 font-medium">
                      <span className="text-muted-foreground mr-1">{isExp ? '▾' : '▸'}</span>
                      {u.username}
                      {u.data_stale && <span className="ml-1.5 px-1 py-0.5 rounded bg-amber-400/15 text-amber-400 text-[9px] align-middle">数据陈旧</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-mono font-medium text-foreground">{u.equity == null ? '—' : formatNumber(u.equity)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-mono">{u.available == null ? '—' : formatNumber(u.available)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-mono">{u.borrowed == null ? '—' : formatNumber(u.borrowed)}</td>
                    <td className={cn('px-3 py-1.5 text-right tabular-nums font-mono', pnlColor(u.unrealized_pnl))}>{u.unrealized_pnl == null ? '—' : formatNumber(u.unrealized_pnl)}</td>
                    <td className={cn('px-3 py-1.5 text-right tabular-nums font-mono', marginColor(u.min_margin_level))}>{u.min_margin_level == null ? '—' : u.min_margin_level.toFixed(2)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{u.account_count}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-mono text-muted-foreground">{formatNumber(u.deployed_notional)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{u.open_positions}</td>
                  </tr>
                  {isExp && u.accounts.length > 0 && (
                    <tr className="bg-[#0a0a10] border-b border-border/30">
                      <td colSpan={9} className="px-3 py-2">
                        <table className="w-full text-[10px] font-mono">
                          <thead>
                            <tr className="text-muted-foreground">
                              <th className="text-left font-medium pr-3 py-0.5">子账户</th>
                              <th className="text-right font-medium pr-3">净值</th>
                              <th className="text-right font-medium pr-3">现货U</th>
                              <th className="text-right font-medium pr-3">全仓净值</th>
                              <th className="text-right font-medium pr-3">已借U</th>
                              <th className="text-right font-medium pr-3">合约权益</th>
                              <th className="text-right font-medium pr-3">合约未实现</th>
                              <th className="text-right font-medium pr-3">保证金水平</th>
                              <th className="text-right font-medium">BNB</th>
                            </tr>
                          </thead>
                          <tbody>
                            {u.accounts.map((a) => (
                              <tr key={a.account_id} className="border-t border-border/20">
                                <td className="pr-3 py-0.5 text-foreground">{a.note || `#${a.account_id}`}</td>
                                <td className="pr-3 text-right tabular-nums text-foreground">{formatNumber(a.equity)}</td>
                                <td className="pr-3 text-right tabular-nums">{formatNumber(a.spot_usdt_free)}</td>
                                <td className="pr-3 text-right tabular-nums">{formatNumber(a.margin_net_usdt)}</td>
                                <td className="pr-3 text-right tabular-nums">{formatNumber(a.margin_usdt_borrowed)}</td>
                                <td className="pr-3 text-right tabular-nums">{formatNumber(a.futures_total)}</td>
                                <td className={cn('pr-3 text-right tabular-nums', pnlColor(a.futures_unrealized_pnl))}>{formatNumber(a.futures_unrealized_pnl)}</td>
                                <td className={cn('pr-3 text-right tabular-nums', marginColor(a.margin_level < 100 ? a.margin_level : null))}>{a.margin_level >= 100 ? '∞' : a.margin_level.toFixed(2)}</td>
                                <td className="text-right tabular-nums">{a.bnb_free.toFixed(4)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* PnL attribution */}
      <div className="rounded-lg border border-border overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 bg-[#111118] border-b border-border">
          <span className="text-[12px] font-semibold text-foreground">盈亏归因</span>
          <div className="flex rounded border border-border overflow-hidden">
            {([['day', '按日'], ['user', '按用户'], ['symbol', '按币种']] as const).map(([k, lbl]) => (
              <button key={k} onClick={() => setAttrBy(k)}
                className={cn('px-2 py-0.5 text-[11px] border-r border-border last:border-0', attrBy === k ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-accent/50')}>
                {lbl}
              </button>
            ))}
          </div>
          <div className="flex rounded border border-border overflow-hidden">
            {[7, 30, 90].map((d) => (
              <button key={d} onClick={() => setAttrDays(d)}
                className={cn('px-2 py-0.5 text-[11px] border-r border-border last:border-0', attrDays === d ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-accent/50')}>
                {d}天
              </button>
            ))}
          </div>
          <span className="text-[10px] text-muted-foreground ml-auto">净 = 平仓利润 + 资金费 − 利息</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[11px] border-collapse">
            <thead>
              <tr className="bg-[#0d0d14] text-muted-foreground border-b border-border">
                <th className="px-3 py-1.5 text-left font-medium">{attrBy === 'user' ? '用户' : attrBy === 'symbol' ? '币种' : '日期'}</th>
                <th className="px-3 py-1.5 text-right font-medium">平仓利润</th>
                <th className="px-3 py-1.5 text-right font-medium">资金费</th>
                <th className="px-3 py-1.5 text-right font-medium">利息</th>
                <th className="px-3 py-1.5 text-right font-medium">净盈亏</th>
                <th className="px-3 py-1.5 text-right font-medium">笔数</th>
              </tr>
            </thead>
            <tbody>
              {attrRows.length === 0 ? (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">暂无数据</td></tr>
              ) : attrRows.map((r) => (
                <tr key={r.key} className="border-b border-border/30 hover:bg-[#1a1a22]/60">
                  <td className="px-3 py-1 font-medium">{attrBy === 'symbol' ? r.label.replace('USDT', '') : r.label}</td>
                  <td className={cn('px-3 py-1 text-right tabular-nums font-mono', pnlColor(r.realized))}>{formatNumber(r.realized)}</td>
                  <td className="px-3 py-1 text-right tabular-nums font-mono text-muted-foreground">{formatNumber(r.funding)}</td>
                  <td className="px-3 py-1 text-right tabular-nums font-mono text-amber-400/80">{formatNumber(r.interest)}</td>
                  <td className={cn('px-3 py-1 text-right tabular-nums font-mono font-medium', pnlColor(r.net))}>{formatNumber(r.net)}</td>
                  <td className="px-3 py-1 text-right tabular-nums text-muted-foreground">{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[10px] text-muted-foreground/50 px-1">
        净值 = 现货USDT + 全仓净资产 + 合约权益 + 合约未实现盈亏。数据来自引擎每 30s 推送的余额快照(只读,不额外请求交易所);
        「数据陈旧」表示该用户暂无快照(引擎未推送/子账户未启用)。「部署名义额」是开仓名义,不等于账户净值。
      </p>
    </div>
  )
}
