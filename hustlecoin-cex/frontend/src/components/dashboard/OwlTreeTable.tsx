import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react'
import { RulesPage } from '@/pages/RulesPage'
import { MoreVertical, Eye, EyeOff } from 'lucide-react'
import { useSpreadStore, type SpreadData } from '@/stores/spreadStore'
import { useBalanceStore, type AccountBalance } from '@/stores/balanceStore'
import { useBanStore } from '@/stores/banStore'
import { useSymbolStatusStore } from '@/stores/symbolStatusStore'
import { useRestrictionStore } from '@/stores/restrictionStore'
import { useMarketDataStore, type MarketInfo } from '@/stores/marketDataStore'
import { useUiStore } from '@/stores/uiStore'
import { cn, formatNumber, pnlColor } from '@/lib/utils'
import { useIsMobile } from '@/hooks/useIsMobile'
import { ContextMenu } from './ContextMenu'

export interface Position {
  id: number
  sub_account_id: number
  account_note?: string
  symbol: string
  status: string
  borrow_qty: string
  open_spread: string
  open_usdt_amount?: string
  cumulative_funding_fee?: string
  cumulative_interest?: string
  funding_rate_ratio?: string
  realized_pnl?: string
  opened_at: string
  close_spread?: string
  futures_long_qty?: string
}

export interface SymbolRuleInfo {
  allow_remove: boolean
  allow_repay: boolean
  open_spread: number | null
  close_spread: number | null
  order_amount: number | null
  close_funding_ratio: number | null
  source: string
}

interface OwlTreeTableProps {
  positions: Position[]
  pushedSymbols: string[]
  pushedAt?: Record<string, number>   // symbol → 推送时刻(unix秒),用于挂单中显示"提币时间"
  symbolRules?: Map<string, SymbolRuleInfo>
  delistingSymbols?: Set<string>
  riskySymbols?: Set<string>
  accountRates?: Record<string, number>   // 逐子账户可借速率 {sub_account_id: req/s}
  onAction: (action: string, symbol: string, position?: Position, extra?: Record<string, unknown>) => void
}

interface SymbolGroup {
  symbol: string
  spread: SpreadData | undefined
  spreadStale: boolean
  positions: Position[]
  totalQty: number
  totalUsdt: number
  totalFunding: number
  totalInterest: number
  groupProfit: number | null
  isPushed: boolean
  openCount: number
  durationHours: number | null
  pushTime: string | null
  pushedAtText: string | null   // 推送时刻格式化("DD HH:MM:SS"),挂单中无持仓时显示
  minMarginLevel: number | null
  ruleInfo: SymbolRuleInfo | null
  futNotional: number | null
  futQty: number | null
  totalMaxBorrow: number | null
  totalFree: number | null
  liquidationPct: number | null
  totalMarginFree: number | null
  totalFutAvail: number | null
}

// 逐账户"被币安API限制":按 updatedAt 推算实时剩余秒(remaining=0=无倒计时,只显文案)
function restrictionFor(
  restrictions: Map<number, { label: string; remaining: number; updatedAt: number }>,
  subAccountId: number,
): { label: string; remaining: number } | undefined {
  const r = restrictions.get(subAccountId)
  if (!r) return undefined
  const remaining = r.remaining > 0 ? Math.max(0, r.remaining - Math.floor((Date.now() - r.updatedAt) / 1000)) : 0
  return { label: r.label, remaining }
}

function fmtSec(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function durationText(opened: string): string {
  if (!opened) return '-'   // 挂单中(无持仓)无开仓时长 → '-',避免 new Date('') → NaNhNaNm
  const diff = Date.now() - new Date(opened).getTime()
  if (!Number.isFinite(diff)) return '-'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  if (h > 24) return `${Math.floor(h / 24)}d${h % 24}h`
  return `${h}h${m}m`
}

function avgDurationHours(positions: Position[]): number | null {
  if (positions.length === 0) return null
  const total = positions.reduce((s, p) => {
    return s + (Date.now() - new Date(p.opened_at).getTime())
  }, 0)
  return total / positions.length / 3600000
}

// ─── Staleness banner (P2-13) ───

function StalenessBanner() {
  const wsConnected = useUiStore((s) => s.wsConnected)
  const lastUpdateTs = useBalanceStore((s) => s.lastUpdateTs)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (wsConnected) { setElapsed(0); return }
    const t = setInterval(() => {
      setElapsed(lastUpdateTs ? Math.floor((Date.now() - lastUpdateTs) / 1000) : 0)
    }, 1000)
    return () => clearInterval(t)
  }, [wsConnected, lastUpdateTs])

  if (wsConnected || elapsed < 30) return null

  return (
    <div className="flex items-center gap-2 px-2 py-1 bg-yellow-500/10 text-yellow-500 text-[10px] border-b border-yellow-500/20 shrink-0">
      数据可能过期 — 最后更新 {elapsed}s 前
    </div>
  )
}

function ruleTooltip(rule: SymbolRuleInfo): string {
  const parts: string[] = []
  if (rule.open_spread != null) parts.push(`开仓: ${rule.open_spread}%`)
  if (rule.close_spread != null) parts.push(`平仓: ${rule.close_spread}%`)
  if (rule.order_amount != null) parts.push(`金额: ${rule.order_amount}`)
  parts.push(`移除: ${rule.allow_remove ? '允许' : '禁止'}`)
  parts.push(`还币: ${rule.allow_repay ? '允许' : '禁止'}`)
  parts.push(`来源: ${rule.source}`)
  return parts.join('\n')
}

// 状态列着色(分级):正常=绿、在途=蓝、队列=黄、等待=紫、异常=橙红、停止=红
const EXEC_STATUSES = new Set(['借币中', '开仓中', '平仓中', '买回中', '还币中', '待还币'])
const ABNORMAL_STATUSES = new Set(['无券', '量不足', '行情异常', '行情陈旧', '借币冷却', '移除冷却', '禁借', '不可交易'])
function statusColorCls(s: string): string {
  if (s === '运行中') return 'text-positive'        // 正常运行(有券+点差达标,挂单借币中)→ 绿
  if (s === '借币停止') return 'text-negative'
  if (s === '借币红') return 'text-red-400'
  if (s === '排队中' || s === '待对冲') return 'text-yellow-400'
  if (EXEC_STATUSES.has(s)) return 'text-blue-400'
  if (s === '点差不符') return 'text-purple-400'     // 等待:点差未达标 → 紫
  if (ABNORMAL_STATUSES.has(s)) return 'text-orange-400'  // 异常:无券/量不足/陈旧等 → 橙
  return 'text-muted-foreground'
}

// 内联参数标签块的一个 chip：灰标签 + 着色值(coinmini 同款 "开0.88 平1.36 …")
function Chip({ label, value, cls }: { label: string; value: React.ReactNode; cls?: string }) {
  return (
    <span className="mr-1.5 whitespace-nowrap">
      <span className="text-foreground">{label}</span>
      <span className={cn('ml-0.5 font-mono tabular-nums', cls)}>{value}</span>
    </span>
  )
}

// ─── CoinHeaderRow ───

const CoinHeaderRow = memo(function CoinHeaderRow({
  group,
  isExpanded,
  compact,
  isMobile,
  isDelisting,
  isRisky,
  symbolStatus,
  marketInfo,
  onToggle,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
  onOpenRules,
}: {
  group: SymbolGroup
  isExpanded: boolean
  compact?: boolean
  isMobile: boolean
  isDelisting?: boolean
  isRisky?: boolean
  borrowDisplayUsdt?: boolean
  symbolStatus?: string | null
  marketInfo?: MarketInfo
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent | React.TouchEvent, symbol: string, position?: Position) => void
  onOpenRules: () => void
}) {
  const hasPos = group.positions.length > 0
  // 开仓点差 = spread_short = (spot_bid-fut_ask)/fut_ask×100 (%)，与交易引擎/规则口径一致
  const openPct = group.spread ? group.spread.spread_short : null
  const closePct = group.spread ? group.spread.spread_long : null
  // 点差陈旧(WS 断流/ts 过期但保留就近值)→ 整块淡化,提示"非实时,仅供参考"
  const spreadStaleCls = group.spreadStale ? 'opacity-50' : ''
  const spreadStaleTitle = group.spreadStale ? '点差非实时(行情断流,显示最近一次有效值)' : undefined

  const coinName = group.symbol
  const dh = group.durationHours
  const dhText = dh != null ? (dh > 24 ? `${Math.floor(dh / 24)}d${Math.floor(dh % 24)}h` : `${Math.floor(dh)}h`) : '-'

  // 真死币:feed 停更(行情陈旧)或盘口异常 → 币名标红 + 💀 图标 + tooltip(陈旧秒数,从 spread.ts 算)
  const isDeadCoin = symbolStatus === '行情陈旧' || symbolStatus === '行情异常'
  const staleSec = group.spread?.ts ? Math.floor((Date.now() - group.spread.ts) / 1000) : null
  const deadTitle = isDeadCoin
    ? (symbolStatus === '行情异常' ? '盘口异常(价格冻结/单腿停更),已停止开仓'
       : `行情停更${staleSec != null ? ` ${staleSec} 秒` : ''},feed 死币,已停止开仓`)
    : undefined

  const rule = group.ruleInfo
  const hasCustomRule = rule && rule.source === 'custom' && (rule.open_spread != null || rule.close_spread != null)
  const isCustom = rule?.source === 'custom'

  // 长按(手机)唤菜单计时/防误触
  const lpTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const lpFired = useRef(false)
  const lpStart = useRef<{ x: number; y: number } | null>(null)

  // 行情参数块:开(实时可开)/平(实时可平)/资/时/限/息
  // 解耦陈旧暗化:仅【开/平】来自点差 feed,陈旧时只暗化这两个;【资/时/限/息】来自独立且健康的
  // market_data(资金费/利率,与点差停更无关),不随点差陈旧一起暗化/置灰,避免「点差断了整格看着全废」。
  const paramBlock = (
    <td className="px-1.5 py-1 text-left">
      <span className={spreadStaleCls} title={spreadStaleTitle}>
        <Chip label="开" value={openPct != null ? formatNumber(openPct, 2) : '-'} cls="text-positive" />
        {!isMobile && <Chip label="平" value={closePct != null ? formatNumber(closePct, 2) : '-'} cls="text-negative" />}
      </span>
      <Chip label="资" value={marketInfo ? (marketInfo.funding_rate * 100).toFixed(4) : '-'}
        cls={marketInfo && marketInfo.funding_rate >= 0 ? 'text-positive' : 'text-negative'} />
      {!isMobile && <Chip label="时" value={marketInfo ? marketInfo.funding_interval : '-'} cls="text-muted-foreground" />}
      {!isMobile && <Chip label="限" value={marketInfo && marketInfo.funding_cap > 0 ? (marketInfo.funding_cap * 100).toFixed(0) : '-'} cls="text-amber-400" />}
      {!isMobile && <Chip label="息" value={marketInfo && marketInfo.daily_interest > 0 ? `${(marketInfo.daily_interest * 100).toFixed(3)}%` : '-'} cls="text-amber-400" />}
    </td>
  )

  return (
    <tr
      id={`symrow-${group.symbol}`}
      className={cn(
        'border-b border-border/30 hover:bg-accent/20 cursor-pointer transition-colors text-[11px]',
        hasPos ? 'bg-[#111118]' : 'bg-[#0d0d14]/50',
      )}
      onClick={() => { if (lpFired.current) return; if (!compact) onToggle(group.symbol) }}
      onDoubleClick={() => onDoubleClick(group.symbol)}
      onContextMenu={(e) => onContextMenu(e, group.symbol)}
      onTouchStart={(e) => {
        // 手机长按(500ms)唤出菜单,替代手机不可用的右键 onContextMenu(桌面右键不变)
        const t = e.touches[0]
        const el = e.currentTarget as HTMLElement   // 捕获行元素(合成事件会被回收,不能在 timeout 里用 e)
        lpStart.current = { x: t.clientX, y: t.clientY }
        lpTimer.current = setTimeout(() => {
          lpFired.current = true
          onMobileMenu({ preventDefault() {}, stopPropagation() {}, currentTarget: el } as unknown as React.MouseEvent, group.symbol)
        }, 500)
      }}
      onTouchMove={(e) => {
        // 移动超阈值(滚动)→ 取消长按
        const t = e.touches[0]
        if (lpStart.current && (Math.abs(t.clientX - lpStart.current.x) > 10 || Math.abs(t.clientY - lpStart.current.y) > 10)) {
          if (lpTimer.current) { clearTimeout(lpTimer.current); lpTimer.current = undefined }
        }
      }}
      onTouchEnd={() => {
        if (lpTimer.current) { clearTimeout(lpTimer.current); lpTimer.current = undefined }
        // 长按已触发菜单 → 抑制随后的 click(避免误触展开)
        if (lpFired.current) { setTimeout(() => { lpFired.current = false }, 50) }
      }}
    >
      {/* expand toggle */}
      <td className="px-1.5 py-1 text-center text-muted-foreground w-5">
        {compact ? '·' : hasPos ? (isExpanded ? '▾' : '▸') : '·'}
      </td>
      {/* 币种 — 退市 / 真死币(行情陈旧/异常,feed 停更)币名标红 + 💀 醒目 */}
      <td className={cn('px-1.5 py-1 font-medium whitespace-nowrap',
        (isDelisting || isDeadCoin) ? 'text-red-500' : 'text-foreground')}
        title={deadTitle}>
        {isRisky && <span className="text-red-500 mr-0.5" title="风险币种">&#9888;</span>}
        {isDeadCoin && <span className="mr-0.5" title={deadTitle}>&#128128;</span>}
        {coinName}
        {hasPos && (
          <span className="ml-1 text-[10px] text-muted-foreground">×{group.openCount}</span>
        )}
        {isMobile && hasPos && (
          <span className="ml-1 text-[10px] text-muted-foreground">{dhText}</span>
        )}
      </td>
      {/* 财务列:汇总行兼"列标签"(coinmini 同款,与标题行合并);数字在子账户行 */}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap" title="合约腿名义价值(USDT)">现-期</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">爆率</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap" title="最大可借: 优先币安 VIP 档借贷上限(borrowLimit,与持U无关、同VIP各账户相同);该币杠杆池无可借库存时,币安 API 直接 -3045 拿不到任何数 → 显示「无券」(真实市场状态)。">最大可借</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">现币</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">借币</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">借币金额</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">风险</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">保证金</td>}
      {!isMobile && <td className="px-1 py-1 text-right text-[10px] text-foreground whitespace-nowrap">可用</td>}
      {/* 参数块(行情) */}
      {paramBlock}
      {/* 推/状态 — 紧凑型: 显运行状态(无子账户行可承载);否则显提币(推送)时间 */}
      {!isMobile && (
        <td className="px-1.5 py-1 text-right whitespace-nowrap text-[10px]">
          {compact && symbolStatus ? (
            <span className={statusColorCls(symbolStatus)}>{symbolStatus}</span>
          ) : group.pushTime ? (
            <span className="text-muted-foreground">推 {group.pushTime}</span>
          ) : group.pushedAtText ? (
            <span className="text-muted-foreground">推 {group.pushedAtText}</span>
          ) : group.isPushed ? (
            <span className="text-primary text-[10px]">已推</span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
      )}
      {/* 资息 — 资息倍率 (signed: 负费率=成本) */}
      {!isMobile && (
        <td className="px-1.5 py-1 text-right tabular-nums font-mono text-[10px]">
          {marketInfo && marketInfo.ratio !== 0 ? (
            <span className={marketInfo.ratio >= 0 ? 'text-positive' : 'text-negative'}>
              {formatNumber(marketInfo.ratio, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 单 — custom rule indicator */}
      {!isMobile && (
        <td
          className="px-0.5 py-1 text-center text-[10px] whitespace-nowrap cursor-pointer hover:bg-accent/30"
          title={rule ? ruleTooltip(rule) : undefined}
          onClick={(e) => { e.stopPropagation(); onDoubleClick(group.symbol) }}
        >
          {hasCustomRule ? (
            <span className="text-amber-400">
              {rule!.open_spread != null ? `开${rule!.open_spread}` : ''}
              {rule!.open_spread != null && rule!.close_spread != null ? ' ' : ''}
              {rule!.close_spread != null ? `平${rule!.close_spread}` : ''}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 速率 — 已下沉到各子账户行(per-account 速率),币种行此列留空占位保持对齐 */}
      {!isMobile && <td className="px-1 py-1"></td>}
      {/* 移/还 — allow_remove / allow_repay 文字指示 */}
      {!isMobile && (
        <td className="px-1 py-1 text-center whitespace-nowrap text-[10px]">
          <span className={rule && rule.allow_remove === false ? 'text-negative' : 'text-positive'}>移</span>
          <span className="mx-0.5 text-muted-foreground/40">·</span>
          <span className={rule && rule.allow_repay === false ? 'text-negative' : 'text-positive'}>还</span>
        </td>
      )}
      {/* 规则类型 — 币种分组行固定显示规则来源(单一规则/通用规则),不显示运行状态;
          运行状态(点差不符等)在各子账户行展示。通用规则→跳全局规则设置;单一规则→打开该币种单一规则弹窗 */}
      {!isMobile && (
        <td
          className="px-1.5 py-1 text-center whitespace-nowrap text-[10px] cursor-pointer hover:bg-accent/30"
          title={isCustom ? (rule ? ruleTooltip(rule) : '点击设置该币种单一规则') : '点击打开全局规则设置(/rules)'}
          onClick={(e) => { e.stopPropagation(); if (isCustom) onDoubleClick(group.symbol); else onOpenRules() }}
        >
          <span className={isCustom ? 'text-amber-400' : 'text-foreground'}>{isCustom ? '单一规则' : '通用规则'}</span>
        </td>
      )}
      {/* mobile action button */}
      {isMobile && (
        <td className="px-0.5 py-1 text-center">
          <button
            onClick={(e) => { e.stopPropagation(); onMobileMenu(e, group.symbol) }}
            className="p-1 rounded hover:bg-accent/50 text-muted-foreground"
          >
            <MoreVertical size={14} />
          </button>
        </td>
      )}
    </tr>
  )
})

// ─── SubAccountRow ───

const SubAccountRow = memo(function SubAccountRow({
  pos,
  spread,
  balance,
  isMobile,
  banRemaining,
  borrowDisplayUsdt,
  symbolStatus,
  marketInfo,
  restriction,
  accountRate,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
}: {
  pos: Position
  spread?: SpreadData
  balance?: AccountBalance
  isMobile: boolean
  banRemaining?: number
  borrowDisplayUsdt?: boolean
  symbolStatus?: string | null
  marketInfo?: MarketInfo
  restriction?: { label: string; remaining: number }
  accountRate?: number
  onContextMenu: (e: React.MouseEvent, symbol: string, position: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent | React.TouchEvent, symbol: string, position?: Position) => void
}) {
  const spreads = useSpreadStore((s) => s.spreads)
  const summary = useBalanceStore((s) => s.summary)
  // 持仓经济参数块:润(净盈亏)/资(累计资金费)/开(开仓点差)/息(当日利率)/累息(累计利息)/平(平仓点差)
  const profit = parseFloat(pos.realized_pnl || '0')
    + parseFloat(pos.cumulative_funding_fee || '0')
    - parseFloat(pos.cumulative_interest || '0')
  const cumFunding = parseFloat(pos.cumulative_funding_fee || '0')
  const cumInterest = parseFloat(pos.cumulative_interest || '0')
  // 已借到币才显示经济参数块(润/资/开/息/累息/平);挂单中(未借到,borrow_qty=0)留空,避免一排无意义的 0/--
  const hasBorrowed = parseFloat(pos.borrow_qty || '0') > 0
  const paramBlock = (
    <td className="px-1.5 py-0.5 text-left">
      {hasBorrowed && <>
        <Chip label="润" value={formatNumber(profit, 2)} cls={pnlColor(profit)} />
        {!isMobile && <Chip label="资" value={formatNumber(cumFunding, 2)} cls={cumFunding >= 0 ? 'text-positive' : 'text-negative'} />}
        <Chip label="开" value={pos.open_spread ? formatNumber(pos.open_spread, 2) : '-'} cls="text-positive" />
        {!isMobile && <Chip label="息" value={marketInfo && marketInfo.daily_interest > 0 ? `${(marketInfo.daily_interest * 100).toFixed(2)}%` : '-'} cls="text-amber-400" />}
        {!isMobile && <Chip label="累息" value={formatNumber(cumInterest, 2)} cls="text-negative" />}
        {!isMobile && <Chip label="平" value={pos.close_spread ? formatNumber(pos.close_spread, 2) : '--'} cls="text-negative" />}
      </>}
    </td>
  )

  const numCell = 'px-1 py-0.5 text-right tabular-nums font-mono text-[10px]'

  return (
    <tr
      className="border-b border-border/10 hover:bg-accent/10 cursor-pointer text-[11px] bg-[#0c0c11]"
      onDoubleClick={() => onDoubleClick(pos.symbol, pos.sub_account_id)}
      onContextMenu={(e) => onContextMenu(e, pos.symbol, pos)}
    >
      <td className="px-1.5 py-0.5"></td>
      {/* 币种 → account note(白色高亮) */}
      <td className="px-1.5 py-0.5 pl-4 text-foreground">
        <div className="whitespace-nowrap">
          ↳ {pos.account_note || `#${pos.sub_account_id}`}
          {isMobile && symbolStatus && (
            <span className={cn('ml-1.5 text-[10px]', statusColorCls(symbolStatus))}>{symbolStatus}</span>
          )}
          {isMobile && !symbolStatus && (
            <span className="ml-1.5 text-[10px] text-muted-foreground">{durationText(pos.opened_at)}</span>
          )}
        </div>
        {/* 被币安 API 限制(账户级)红字提示 */}
        {isMobile && restriction && (
          <div className="mt-0.5 text-[10px] text-red-500 font-medium">⚠ 被限制:{restriction.label}{restriction.remaining > 0 ? ` ${fmtSec(restriction.remaining)}` : ''}</div>
        )}
        {/* 移动端紧凑数据行 — 对齐 PC 逐账户列(现期/爆率/有效可借/现币/借币/借币金额/风险) */}
        {isMobile && (() => {
          const sm = balance?.symbol_margin?.[pos.symbol]
          const futVal = parseFloat(pos.futures_long_qty || '0') * (spread?.fut_bid ?? 0)
          const blow = summary?.masterFuturesLiqPct ?? null  // 爆率=主账户合约户维持保证金率(与桌面同源)
          const px = spread?.spot_bid ?? 0
          const eff = sm ? (sm.effective_borrowable ?? sm.max_borrowable) : null
          const noInv = sm?.no_inventory && !(sm.max_borrowable > 0)
          return (
            <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[10px] tabular-nums font-mono leading-tight">
              <span className="text-muted-foreground/60">爆<span className={cn('ml-0.5', blow != null ? (blow > 80 ? 'text-negative' : blow > 50 ? 'text-yellow-400' : 'text-positive') : 'text-foreground')}>{blow != null ? `${formatNumber(blow, 1)}%` : '-'}</span></span>
              <span className="text-muted-foreground/60">可借{noInv
                ? <span className="ml-0.5 text-amber-500/90">无券</span>
                : <span className="ml-0.5 text-sky-300/90">{eff != null ? (borrowDisplayUsdt ? formatNumber(eff * px, 0) : formatNumber(eff, 2)) : '-'}</span>}</span>
              <span className="text-muted-foreground/60">现币<span className="ml-0.5 text-foreground">{sm?.free != null ? formatNumber(sm.free, 4) : '-'}</span></span>
              <span className="text-muted-foreground/60">借<span className="ml-0.5 text-foreground">{sm?.borrowed != null ? formatNumber(sm.borrowed, 4) : '-'}</span></span>
              <span className="text-muted-foreground/60">额<span className="ml-0.5 text-foreground">{(() => { const v = (sm?.borrowed ?? 0) * px; return v > 0.01 ? formatNumber(v, 0) : '-' })()}</span></span>
              <span className="text-muted-foreground/60">险<span className={cn('ml-0.5', balance ? (balance.margin_level > 2 ? 'text-positive' : balance.margin_level > 1.3 ? 'text-yellow-400' : 'text-negative') : 'text-foreground')}>{balance ? formatNumber(balance.margin_level, 2) : '-'}</span></span>
              {futVal > 0 && <span className="text-muted-foreground/60">现期<span className="ml-0.5 text-foreground">{formatNumber(futVal, 0)}</span></span>}
            </div>
          )
        })()}
      </td>
      {/* 现-期 — 主账户合约持仓币数(优先),降级子账户持仓 */}
      {!isMobile && (() => {
        // 优先用主账户合约持仓(hedge_via_master模式),无则降级子账户
        const masterQty = summary?.masterFuturesPositions?.[pos.symbol] ?? 0
        const qty = masterQty !== 0 ? Math.abs(masterQty) : parseFloat(pos.futures_long_qty || '0')
        const isMaster = masterQty !== 0
        const price = spread?.fut_bid ?? 0
        const val = qty * price
        const title = qty > 0
          ? `${isMaster ? '主账户' : '子账户'}合约持仓 · 名义价值: ${formatNumber(val, 2)} USDT`
          : undefined
        return (
          <td className={numCell} title={title}>
            {qty > 0 ? formatNumber(qty, 4) : '-'}
          </td>
        )
      })()}
      {/* 爆率 — 主账户合约户维持保证金率(币安标准,hedge_via_master 下真正的强平风险在主账户合约;全表同值) */}
      {!isMobile && (
        <td className={numCell}>
          {summary?.masterFuturesLiqPct != null ? (() => {
            const pct = summary.masterFuturesLiqPct as number
            return (
              <span className={pct > 80 ? 'text-negative' : pct > 50 ? 'text-yellow-400' : 'text-positive'}>
                {formatNumber(pct, 1)}%
              </span>
            )
          })() : '-'}
        </td>
      )}
      {/* 有效可借 — 优先显示 VIP 档借贷上限(borrow_limit,与持U无关),无则降级 effective_borrowable */}
      {!isMobile && (
        <td className={numCell}>
          {(() => {
            const sm = balance?.symbol_margin?.[pos.symbol]
            if (!sm) return '-'
            // 该币杠杆池无可借库存 → 币安 maxBorrowable 直接 -3045 拿不到任何数 → 「无券」(真实市场状态)
            if (sm.no_inventory && !((sm.borrow_limit ?? 0) > 0) && !(sm.max_borrowable > 0)) {
              return <span className="text-amber-500/80" title="币安杠杆池当前无该币可借库存(API -3045)">无券</span>
            }
            const px = spread?.spot_bid ?? 0
            // 最大可借 = 优先 borrowLimit(VIP档借贷上限,与持U无关、恒定);无则降级 maxBorrowable(amount,实际可借)
            const val = (sm.borrow_limit ?? 0) > 0 ? sm.borrow_limit! : (sm.max_borrowable ?? sm.effective_borrowable ?? 0)
            const isBorrowLimit = (sm.borrow_limit ?? 0) > 0
            const shown = borrowDisplayUsdt ? formatNumber(val * px, 0) : formatNumber(val, 2)
            const title = isBorrowLimit
              ? '币安 VIP 档借贷上限(borrowLimit,与持U无关、同VIP各账户相同)'
              : `币安实际最大可借(maxBorrowable amount)${sm.borrow_cap_reason ? ` · 受限于: ${sm.borrow_cap_reason}` : ''}`
            return <span className={isBorrowLimit ? 'text-emerald-400/90' : ''} title={title}>{shown}</span>
          })()}
        </td>
      )}
      {/* 现币 */}
      {!isMobile && (
        <td className={numCell}>
          {balance?.symbol_margin?.[pos.symbol]?.free != null
            ? formatNumber(balance.symbol_margin[pos.symbol].free, 4)
            : '-'}
        </td>
      )}
      {/* 借币 — 币安杠杆户实时借币本金(sm.borrowed),非 position 静态快照,随利息/部分还币/还币即时变 */}
      {!isMobile && (() => {
        const sm = balance?.symbol_margin?.[pos.symbol]
        return <td className={numCell}>{sm?.borrowed != null ? formatNumber(sm.borrowed, 4) : '-'}</td>
      })()}
      {/* 借币金额 — 借币(sm.borrowed)× 此币当前U值(spot_bid),实时变动 */}
      {!isMobile && (() => {
        const sm = balance?.symbol_margin?.[pos.symbol]
        const borrowed = sm?.borrowed ?? 0
        const spotPrice = spread?.spot_bid ?? 0
        const val = borrowed * spotPrice
        return <td className={numCell}>{val > 0.01 ? formatNumber(val, 0) : '-'}</td>
      })()}
      {/* 风险 — margin level */}
      {!isMobile && (
        <td className={numCell}>
          {balance ? (
            <span className={balance.margin_level > 2 ? 'text-positive' : balance.margin_level > 1.3 ? 'text-yellow-400' : 'text-negative'}>
              {formatNumber(balance.margin_level, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 保证金 — BNB U值 + USDT */}
      {!isMobile && (() => {
        if (!balance) return <td className={numCell}>-</td>
        const bnbPrice = spreads.get('BNBUSDT')?.spot_bid ?? 0
        const bnbVal = balance.bnb_free * bnbPrice
        const total = bnbVal + balance.margin_usdt_free
        return <td className={numCell}>{formatNumber(total, 0)}</td>
      })()}
      {/* 可用 — 杠杆账户可用USDT(可用来借币) */}
      {!isMobile && (
        <td className={numCell}>
          {balance ? formatNumber(balance.margin_usdt_free, 0) : '-'}
        </td>
      )}
      {/* 参数块(持仓经济) */}
      {paramBlock}
      {/* 推/状态 — 子账户行状态(三态互斥):被限流=API错误(红);正在借/已借到=借币(青);
          其余等待态(运行中/点差不符/无券…)保留原状态词;无状态显持仓时长 */}
      {!isMobile && (
        <td className="px-1.5 py-0.5 text-right whitespace-nowrap text-[10px]">
          {restriction ? (
            <span className="text-red-500 font-medium">API错误</span>
          ) : (symbolStatus && EXEC_STATUSES.has(symbolStatus)) ? (
            <span className="text-sky-400">借币</span>
          ) : symbolStatus ? (
            <span className={statusColorCls(symbolStatus)}>{symbolStatus}</span>
          ) : (
            <span className="text-muted-foreground">{durationText(pos.opened_at)}</span>
          )}
        </td>
      )}
      {/* 资息 — 该持仓资息倍率(保留) */}
      {!isMobile && (
        <td className={numCell}>
          {pos.funding_rate_ratio != null && parseFloat(pos.funding_rate_ratio) !== 0 ? (
            <span className={parseFloat(pos.funding_rate_ratio) >= 0 ? 'text-positive' : 'text-negative'}>
              {formatNumber(pos.funding_rate_ratio, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 单 — 子账户行留空 */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 速率 — 该子账户 per-account 可借速率(各账户因 UID 消耗不同而不同) */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px] text-foreground"
            title="该子账户当前 UID 权重余量下每秒可发起的借币次数(各账户独立)">
          {accountRate != null && accountRate > 0 ? `${accountRate.toFixed(2)}次` : '-'}
        </td>
      )}
      {/* 移/还 — 封禁倒计时 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-center whitespace-nowrap text-[10px]">
          {banRemaining != null && banRemaining > 0 ? (
            <span className="text-red-500 font-mono">{Math.floor(banRemaining / 60)}:{String(banRemaining % 60).padStart(2, '0')}</span>
          ) : (
            <span className="text-muted-foreground/40">—</span>
          )}
        </td>
      )}
      {/* 规则列 — 子账户行复用此列显示"被币安API限制"红字提示(账户级) */}
      {!isMobile && (
        <td className="px-1.5 py-0.5 text-center whitespace-nowrap text-[10px]">
          {restriction ? (
            <span className="text-red-500 font-medium" title={`被币安 API 限制:${restriction.label}`}>
              {restriction.label}{restriction.remaining > 0 ? ` ${fmtSec(restriction.remaining)}` : ''}
            </span>
          ) : null}
        </td>
      )}
      {/* mobile action button */}
      {isMobile && (
        <td className="px-0.5 py-0.5 text-center">
          <button
            onClick={(e) => { e.stopPropagation(); onMobileMenu(e, pos.symbol, pos) }}
            className="p-1 rounded hover:bg-accent/50 text-muted-foreground"
          >
            <MoreVertical size={12} />
          </button>
        </td>
      )}
    </tr>
  )
})

// ─── Main OwlTreeTable ───

const FILTER_KEY = 'hc_filter_positions_only'
const BORROW_DISPLAY_KEY = 'hc_borrow_display_mode'
const COMPACT_KEY = 'hc_compact_view'
// 币种行点差陈旧阈值(ms):某币 ts 落后全表最新 ts 超过此值视为陈旧(就近值变灰),与 /spreads 默认 300s 一致
const DASH_SPREAD_STALE_MS = 300_000

export function OwlTreeTable({ positions, pushedSymbols, pushedAt, symbolRules, delistingSymbols, riskySymbols, accountRates, onAction }: OwlTreeTableProps) {
  const spreads = useSpreadStore((s) => s.spreads)
  const spreadsLastTs = useSpreadStore((s) => s.lastUpdateTs)
  // 就近点差缓存: WS 断流/某币 ts 过期时,保留最后一次有效点差(不闪不清零,标记陈旧),
  // 避免币种行点差因瞬时缺数据而变 '-' 或跳动。仅"从未有过数据"才落到 undefined。
  const lastGoodSpreadRef = useRef<Map<string, SpreadData>>(new Map())
  const balances = useBalanceStore((s) => s.balances)
  const bans = useBanStore((s) => s.bans)
  const symbolStatuses = useSymbolStatusStore((s) => s.statuses)
  const restrictions = useRestrictionStore((s) => s.restrictions)
  const marketData = useMarketDataStore((s) => s.marketData)
  const wsConnected = useUiStore((s) => s.wsConnected)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [showPositionsOnly, setShowPositionsOnly] = useState(() => {
    try { return localStorage.getItem(FILTER_KEY) === 'true' } catch { return false }
  })
  const [compact, setCompact] = useState(() => {
    try { return localStorage.getItem(COMPACT_KEY) === 'true' } catch { return false }
  })
  const toggleCompact = useCallback(() => {
    setCompact(prev => {
      const next = !prev
      try { localStorage.setItem(COMPACT_KEY, String(next)) } catch { /* ignore */ }
      return next
    })
  }, [])
  const borrowDisplayUsdt = useMemo(() => {
    try { return localStorage.getItem(BORROW_DISPLAY_KEY) === 'usdt' } catch { return false }
  }, [])
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; symbol: string; position?: Position
  } | null>(null)
  const isMobile = useIsMobile()

  // 推送后定位:OwlTopBar 推送成功派发 pushed:focus(detail=symbol),滚动到该币汇总行并短暂高亮,
  // 修复"再推一个已在列表的币没反应"。元素 id=symrow-{symbol};best-effort(被搜索/仅持仓过滤掉则不滚)。
  useEffect(() => {
    const onFocus = (e: Event) => {
      const sym = (e as CustomEvent).detail as string
      if (!sym) return
      setTimeout(() => {
        const el = document.getElementById(`symrow-${sym}`)
        if (!el) return
        el.scrollIntoView({ block: 'center', behavior: 'smooth' })
        el.style.transition = 'background-color 0.4s'
        el.style.backgroundColor = 'rgba(99,102,241,0.22)'
        setTimeout(() => { el.style.backgroundColor = '' }, 1800)
      }, 150)
    }
    window.addEventListener('pushed:focus', onFocus)
    return () => window.removeEventListener('pushed:focus', onFocus)
  }, [])

  const pushedSet = useMemo(() => new Set(pushedSymbols), [pushedSymbols])

  const balanceMap = useMemo(() => {
    const m = new Map<number, AccountBalance>()
    for (const b of balances) m.set(b.account_id, b)
    return m
  }, [balances])

  // C4: tick every second to update ban countdowns
  const [, setTick] = useState(0)
  useEffect(() => {
    if (bans.size === 0) return
    const t = setInterval(() => setTick(n => n + 1), 1000)
    return () => clearInterval(t)
  }, [bans.size])

  const toggleFilter = useCallback(() => {
    setShowPositionsOnly(prev => {
      const next = !prev
      try { localStorage.setItem(FILTER_KEY, String(next)) } catch { /* ignore */ }
      return next
    })
  }, [])

  const groups = useMemo(() => {
    const bySymbol = new Map<string, Position[]>()
    for (const p of positions) {
      const list = bySymbol.get(p.symbol) || []
      list.push(p)
      bySymbol.set(p.symbol, list)
    }

    // 并入"有自定义单一规则(source=custom)"的币:即便无持仓、未推送,也显示其操作台行
    // (修复"操作台被自动下架后,设单一规则也救不回";只认 custom,避免 scan/global 默认刷屏)
    const ruleSymbols = symbolRules
      ? [...symbolRules.entries()].filter(([, r]) => r.source === 'custom').map(([s]) => s)
      : []
    const allSymbols = new Set([...bySymbol.keys(), ...pushedSet, ...ruleSymbols])
    const q = search.toUpperCase()
    const result: SymbolGroup[] = []

    for (const symbol of allSymbols) {
      if (q && !symbol.includes(q)) continue
      // 就近点差: store 有值就用并刷新缓存(ts 过期则标陈旧);store 已剔除该币(死币/断流)
      // 则回退最后一次有效值并标陈旧。两者皆无才 undefined → 显示 '-'。
      const liveSp = spreads.get(symbol)
      let sp = liveSp
      let spreadStale = false
      if (liveSp) {
        lastGoodSpreadRef.current.set(symbol, liveSp)
        spreadStale = spreadsLastTs > 0 && spreadsLastTs - liveSp.ts > DASH_SPREAD_STALE_MS
      } else {
        const cached = lastGoodSpreadRef.current.get(symbol)
        if (cached) { sp = cached; spreadStale = true }
      }
      const pos = bySymbol.get(symbol) || []

      if (showPositionsOnly && pos.length === 0) continue

      const totalQty = pos.reduce((s, p) => s + parseFloat(p.borrow_qty || '0'), 0)
      const totalUsdt = pos.reduce((s, p) => s + parseFloat(p.open_usdt_amount || '0'), 0)
      const totalFunding = pos.reduce((s, p) => s + parseFloat(p.cumulative_funding_fee || '0'), 0)
      const totalInterest = pos.reduce((s, p) => s + parseFloat(p.cumulative_interest || '0'), 0)
      // 持仓净盈亏 = 已实现 + 资金费收入 − 借币利息
      const groupProfit = pos.length > 0
        ? pos.reduce((s, p) => s
            + parseFloat(p.realized_pnl || '0')
            + parseFloat(p.cumulative_funding_fee || '0')
            - parseFloat(p.cumulative_interest || '0'), 0)
        : null
      const dh = avgDurationHours(pos)

      // Aggregate min margin level across accounts for this symbol
      const accountIds = [...new Set(pos.map(p => p.sub_account_id))]
      const marginLevels = accountIds
        .map(id => balanceMap.get(id)?.margin_level)
        .filter((v): v is number => v != null && v > 0)
      const minMarginLevel = marginLevels.length > 0 ? Math.min(...marginLevels) : null

      const earliest = pos.length > 0
        ? pos.reduce((min, p) => {
            const t = new Date(p.opened_at).getTime()
            return t < min ? t : min
          }, Infinity)
        : null
      // 推送时间:日 + HH:MM:SS(coinmini 同款 "推06 16:08:56")
      const fmtTime = (ms: number) => {
        const d = new Date(ms)
        const p2 = (n: number) => String(n).padStart(2, '0')
        return `${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`
      }
      const pushTime = earliest && earliest < Infinity ? fmtTime(earliest) : null
      // 提币(推送)时刻:无持仓的挂单中币用后端记录的 pushed_at(unix秒)格式化展示
      const pushedAtTs = pushedAt?.[symbol]
      const pushedAtText = pushedAtTs ? fmtTime(pushedAtTs * 1000) : null

      const ruleInfo = symbolRules?.get(symbol) ?? null

      const futNotional = pos.length > 0
        ? pos.reduce((s, p) => {
            const qty = parseFloat(p.futures_long_qty || '0')
            const price = sp?.fut_bid ?? 0
            return s + qty * price
          }, 0) || null
        : null
      const futQty = pos.length > 0
        ? pos.reduce((s, p) => s + parseFloat(p.futures_long_qty || '0'), 0) || null
        : null

      let totalMaxBorrow: number | null = null
      let totalFree: number | null = null
      {
        // Positioned symbol → its accounts; pushed-only symbol → all enabled accounts.
        const ids = pos.length > 0
          ? [...new Set(pos.map(p => p.sub_account_id))]
          : [...balanceMap.keys()]
        let mb = 0, fr = 0, hasMb = false, hasFr = false
        for (const id of ids) {
          const sm = balanceMap.get(id)?.symbol_margin?.[symbol]
          if (sm) {
            // 聚合「有效可借」与子账户行口径一致(回退理论上限)
            const eff = sm.effective_borrowable ?? sm.max_borrowable
            if (eff > 0) { mb += eff; hasMb = true }
            if (sm.free > 0) { fr += sm.free; hasFr = true }
          }
        }
        totalMaxBorrow = hasMb ? mb : null
        totalFree = hasFr ? fr : null
      }

      const liquidationLevels = accountIds
        .map(id => balanceMap.get(id)?.margin_level)
        .filter((v): v is number => v != null && v > 0)
      const liquidationPct = liquidationLevels.length > 0
        ? (1.1 / Math.min(...liquidationLevels)) * 100
        : null

      // 保证金 = 杠杆账户总权益(净资产USDT)，回退到可用USDT
      const totalMarginFree = pos.length > 0
        ? [...new Set(pos.map(p => p.sub_account_id))].reduce((s, id) => {
            const b = balanceMap.get(id)
            return s + (b?.margin_net_usdt ?? b?.margin_usdt_free ?? 0)
          }, 0) || null
        : null

      const totalFutAvail = pos.length > 0
        ? [...new Set(pos.map(p => p.sub_account_id))].reduce((s, id) => {
            return s + (balanceMap.get(id)?.futures_available ?? 0)
          }, 0) || null
        : null

      result.push({
        symbol, spread: sp, spreadStale, positions: pos,
        totalQty, totalUsdt, totalFunding, totalInterest, groupProfit,
        isPushed: pushedSet.has(symbol),
        openCount: pos.length,
        durationHours: dh,
        pushTime,
        pushedAtText,
        minMarginLevel,
        ruleInfo,
        futNotional,
        futQty,
        totalMaxBorrow,
        totalFree,
        liquidationPct,
        totalMarginFree,
        totalFutAvail,
      })
    }

    result.sort((a, b) => {
      if (a.positions.length !== b.positions.length) return b.positions.length - a.positions.length
      if (a.isPushed !== b.isPushed) return a.isPushed ? -1 : 1
      return (a.symbol < b.symbol ? -1 : 1)
    })

    return result
  }, [spreads, spreadsLastTs, positions, search, pushedSet, pushedAt, showPositionsOnly, balanceMap, symbolRules])

  const toggle = useCallback((symbol: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }, [])

  const handleContextMenu = useCallback((e: React.MouseEvent, symbol: string, position?: Position) => {
    e.preventDefault()
    setContextMenu({ x: e.clientX, y: e.clientY, symbol, position })
  }, [])

  const handleMobileMenu = useCallback((e: React.MouseEvent | React.TouchEvent, symbol: string, position?: Position) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setContextMenu({ x: rect.left, y: rect.bottom, symbol, position })
  }, [])

  const handleDoubleClick = useCallback((symbol: string, subAccountId?: number) => {
    onAction('set_rule', symbol, undefined, subAccountId ? { initialAccountId: subAccountId } : undefined)
  }, [onAction])

  const [showRules, setShowRules] = useState(false)
  const handleOpenRules = useCallback(() => setShowRules(true), [])

  useEffect(() => {
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  // expanded 集合记录"与默认态相反"的币。全展=所有币展开;全收=所有币折叠。
  const expandAll = useCallback(() => {
    // 让默认折叠的(持仓币)进集合反转为展开;默认展开的(挂单币)不进集合即保持展开
    setExpanded(new Set(groups.filter(g => !(g.isPushed && g.positions.length === 0)).map(g => g.symbol)))
  }, [groups])

  const collapseAll = useCallback(() => {
    // 让默认展开的(挂单币)进集合反转为折叠;默认折叠的(持仓币)不进集合即保持折叠
    setExpanded(new Set(groups.filter(g => g.isPushed && g.positions.length === 0).map(g => g.symbol)))
  }, [groups])

  const posCount = groups.filter(g => g.positions.length > 0).length
  const totalUsdt = groups.reduce((s, g) => s + g.totalUsdt, 0)
  const totalFunding = groups.reduce((s, g) => s + g.totalFunding, 0)
  const totalInterest = groups.reduce((s, g) => s + g.totalInterest, 0)
  const totalProfit = totalFunding - totalInterest

  const colCount = isMobile ? 4 : 18

  return (
    <div className="flex flex-col h-full">
      {/* Staleness banner */}
      <StalenessBanner />

      {/* Summary bar */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 py-1.5 text-[11px] text-muted-foreground border-b border-border shrink-0">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索..."
          className="w-28 bg-transparent border border-border rounded px-1.5 py-0.5 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
        />
        <button
          onClick={expandAll}
          className="px-1.5 py-0.5 rounded border border-border text-[10px] hover:bg-accent/50"
          title="全部展开"
        >全展</button>
        <button
          onClick={collapseAll}
          className="px-1.5 py-0.5 rounded border border-border text-[10px] hover:bg-accent/50"
          title="全部折叠"
        >全收</button>
        <button
          onClick={toggleFilter}
          className={cn(
            'px-1.5 py-0.5 rounded border text-[10px] inline-flex items-center gap-1',
            showPositionsOnly
              ? 'border-primary text-primary bg-primary/10'
              : 'border-border hover:bg-accent/50',
          )}
          title={showPositionsOnly ? '显示全部币种' : '仅显示有持仓/借币'}
        >
          {showPositionsOnly ? <Eye size={10} /> : <EyeOff size={10} />}
          {showPositionsOnly ? '显' : '隐'}
        </button>
        <button
          onClick={toggleCompact}
          className={cn(
            'px-1.5 py-0.5 rounded border text-[10px]',
            compact ? 'border-primary text-primary bg-primary/10' : 'border-border hover:bg-accent/50',
          )}
          title={compact ? '切换为树形多账户视图' : '切换为紧凑单账户视图（折叠子账户）'}
        >{compact ? '紧凑' : '树形'}</button>
        <span>持仓 <span className="text-foreground">{posCount}</span> 币种</span>
        <span>推送 <span className="text-primary">{pushedSymbols.length}</span></span>
        <span>金额 <span className="text-foreground font-mono">{formatNumber(totalUsdt, 0)}</span></span>
        <span className={pnlColor(totalFunding)}>资金费 {formatNumber(totalFunding)}</span>
        <span className="text-negative">利息 {formatNumber(totalInterest)}</span>
        <span className={cn('font-medium', pnlColor(totalProfit))}>利润 {formatNumber(totalProfit)}</span>
      </div>

      {/* Table */}
      <div className={cn('flex-1 overflow-auto', !wsConnected && 'opacity-60')}>
        <table className={cn('w-full', !isMobile && 'min-w-[1100px]')}>
          {/* 标题行已与 CoinHeaderRow 合并(coinmini 同款):每个币种汇总行兼列标签,不再单独 sticky 表头 */}
          <tbody>
            {groups.map((g) => {
              // 挂单中(已推送无持仓)默认展开显示各子账户状态;expanded 集合记录"被手动 toggle 过"的币
              // → 实际展开 = 默认态 XOR 手动 toggle(挂单币默认开、持仓币默认关,均可手动反转)。
              const defaultOpen = g.isPushed && g.positions.length === 0
              const isExp = !compact && (expanded.has(g.symbol) ? !defaultOpen : defaultOpen)
              return (
                <CoinGroupRows
                  key={g.symbol}
                  group={g}
                  isExpanded={isExp}
                  compact={compact}
                  isMobile={isMobile}
                  isDelisting={delistingSymbols?.has(g.symbol)}
                  isRisky={riskySymbols?.has(g.symbol)}
                  borrowDisplayUsdt={borrowDisplayUsdt}
                  balanceMap={balanceMap}
                  spreads={spreads}
                  bans={bans}
                  symbolStatuses={symbolStatuses}
                  restrictions={restrictions}
                  marketData={marketData}
                  accountRates={accountRates}
                  onToggle={toggle}
                  onContextMenu={handleContextMenu}
                  onDoubleClick={handleDoubleClick}
                  onMobileMenu={handleMobileMenu}
                  onOpenRules={handleOpenRules}
                />
              )
            })}
            {groups.length === 0 && (
              <tr>
                <td colSpan={colCount} className="py-8 text-center text-muted-foreground text-xs">
                  {search ? '未找到匹配币种' : showPositionsOnly ? '没有持仓币种' : '等待数据...'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          symbol={contextMenu.symbol}
          position={contextMenu.position}
          isPushed={pushedSet.has(contextMenu.symbol)}
          isAccountRow={!!contextMenu.position}
          subAccountId={contextMenu.position?.sub_account_id}
          onAction={(action, extra) => {
            onAction(action, contextMenu.symbol, contextMenu.position, extra)
            setContextMenu(null)
          }}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* 通用规则 → 弹窗模态(承载 RulesPage,与主界面一致,不再整页跳转 /rules) */}
      {showRules && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2"
          onClick={() => setShowRules(false)}>
          <div className="w-full max-w-[1100px] max-h-[92vh] overflow-y-auto overflow-x-hidden rounded-lg border border-border bg-background shadow-2xl"
            onClick={(e) => e.stopPropagation()}>
            <RulesPage onClose={() => setShowRules(false)} />
          </div>
        </div>
      )}
    </div>
  )
}

const CoinGroupRows = memo(function CoinGroupRows({
  group,
  isExpanded,
  compact,
  isMobile,
  isDelisting,
  isRisky,
  borrowDisplayUsdt,
  balanceMap,
  spreads,
  bans,
  symbolStatuses,
  restrictions,
  marketData,
  accountRates,
  onToggle,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
  onOpenRules,
}: {
  group: SymbolGroup
  isExpanded: boolean
  compact?: boolean
  isMobile: boolean
  isDelisting?: boolean
  isRisky?: boolean
  borrowDisplayUsdt: boolean
  balanceMap: Map<number, AccountBalance>
  spreads: Map<string, SpreadData>
  bans: Map<string, { remaining: number; updatedAt: number }>
  symbolStatuses: Map<string, string>
  restrictions: Map<number, { label: string; remaining: number; updatedAt: number }>
  marketData: Map<string, MarketInfo>
  accountRates?: Record<string, number>
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent | React.TouchEvent, symbol: string, position?: Position) => void
  onOpenRules: () => void
}) {
  const headerStatus = useMemo(() => {
    const priority = ['借币停止', '借币红', '排队中', '借币中', '开仓中', '平仓中', '买回中', '还币中', '运行中', '无券', '点差不符', '量不足', '行情陈旧', '行情异常']
    // 状态口径与下方"显示哪些子账户行"保持并集一致:持仓账户 ∪ (该币被推送/有生效规则时的所有 enabled 账户)
    const ids = new Set<number>()
    group.positions.forEach(p => ids.add(p.sub_account_id))
    if (group.isPushed || group.ruleInfo != null) {
      for (const id of balanceMap.keys()) ids.add(id)
    }
    const keys = [...ids].map(id => `${id}:${group.symbol}`)
    for (const s of priority) {
      if (keys.some(k => symbolStatuses.get(k) === s)) return s
    }
    return null
  }, [group.positions, group.isPushed, group.ruleInfo, group.symbol, symbolStatuses, balanceMap])

  return (
    <>
      <CoinHeaderRow
        group={group}
        isExpanded={isExpanded}
        compact={compact}
        isMobile={isMobile}
        isDelisting={isDelisting}
        isRisky={isRisky}
        borrowDisplayUsdt={borrowDisplayUsdt}
        symbolStatus={headerStatus}
        marketInfo={marketData.get(group.symbol)}
        onToggle={onToggle}
        onContextMenu={onContextMenu}
        onDoubleClick={onDoubleClick}
        onMobileMenu={onMobileMenu}
        onOpenRules={onOpenRules}
      />
      {isExpanded && group.positions.map((pos) => {
        const banKey = `${pos.sub_account_id}:${pos.symbol}`
        const banEntry = bans.get(banKey)
        const banRemaining = banEntry
          ? Math.max(0, banEntry.remaining - Math.floor((Date.now() - banEntry.updatedAt) / 1000))
          : undefined
        const posStatus = symbolStatuses.get(banKey) ?? null
        const posRestriction = restrictionFor(restrictions, pos.sub_account_id)
        return (
          <SubAccountRow
            key={pos.id}
            pos={pos}
            spread={spreads.get(pos.symbol)}
            balance={balanceMap.get(pos.sub_account_id)}
            isMobile={isMobile}
            banRemaining={banRemaining}
            borrowDisplayUsdt={borrowDisplayUsdt}
            symbolStatus={posStatus}
            restriction={posRestriction}
            marketInfo={marketData.get(pos.symbol)}
            accountRate={accountRates?.[String(pos.sub_account_id)]}
            onContextMenu={onContextMenu}
            onDoubleClick={onDoubleClick}
            onMobileMenu={onMobileMenu}
          />
        )
      })}
      {/* 子账户行渲染并集:除上方"有持仓"账户外,只要该币被推送或有生效规则(全局/单一),
          就把其余 enabled 子账户(去重)也造最小伪 position 显示(账户名+余额+逐账户状态)。
          修复"只有全局规则、别的账户已持仓时,该子账户整行不显示"(问题2;原 positions.length===0 互斥闸)。 */}
      {isExpanded && (group.isPushed || group.ruleInfo != null) &&
        [...balanceMap.values()]
          .filter((bal) => !group.positions.some((p) => p.sub_account_id === bal.account_id))
          .map((bal) => {
          const acctStatus = symbolStatuses.get(`${bal.account_id}:${group.symbol}`) ?? null
          const acctRestriction = restrictionFor(restrictions, bal.account_id)
          const pseudo: Position = {
            id: -bal.account_id,                  // 负 id 保证 key 不与真实 position 冲突
            sub_account_id: bal.account_id,
            account_note: bal.note,
            symbol: group.symbol,
            status: 'PUSHED',
            borrow_qty: '0',
            open_spread: '0',
            opened_at: '',
          }
          return (
            <SubAccountRow
              key={`pushed-${bal.account_id}`}
              pos={pseudo}
              spread={spreads.get(group.symbol)}
              balance={bal}
              isMobile={isMobile}
              borrowDisplayUsdt={borrowDisplayUsdt}
              symbolStatus={acctStatus}
              restriction={acctRestriction}
              marketInfo={marketData.get(group.symbol)}
              accountRate={accountRates?.[String(bal.account_id)]}
              onContextMenu={onContextMenu}
              onDoubleClick={onDoubleClick}
              onMobileMenu={onMobileMenu}
            />
          )
        })}
    </>
  )
})
