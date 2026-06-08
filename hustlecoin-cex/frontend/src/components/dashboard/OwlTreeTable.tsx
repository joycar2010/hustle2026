import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react'
import { MoreVertical, Eye, EyeOff } from 'lucide-react'
import { useSpreadStore, type SpreadData } from '@/stores/spreadStore'
import { useBalanceStore, type AccountBalance } from '@/stores/balanceStore'
import { useBanStore } from '@/stores/banStore'
import { useSymbolStatusStore } from '@/stores/symbolStatusStore'
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
  symbolRules?: Map<string, SymbolRuleInfo>
  delistingSymbols?: Set<string>
  riskySymbols?: Set<string>
  throttleRate?: number
  onAction: (action: string, symbol: string, position?: Position, extra?: Record<string, unknown>) => void
}

interface SymbolGroup {
  symbol: string
  spread: SpreadData | undefined
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

function useFlash(_key: string, value: string | number | undefined) {
  const prev = useRef(value)
  const [flashing, setFlashing] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    if (prev.current !== value && prev.current !== undefined && value !== undefined) {
      setFlashing(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setFlashing(false), 1000)
    }
    prev.current = value
  }, [value])

  return flashing ? 'animate-flash' : ''
}

function durationText(opened: string): string {
  const diff = Date.now() - new Date(opened).getTime()
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

// 状态列着色：规则态 + 执行/队列态
const EXEC_STATUSES = new Set(['借币中', '开仓中', '平仓中', '买回中', '还币中', '待还币'])
function statusColorCls(s: string): string {
  if (s === '借币停止') return 'text-negative'
  if (s === '借币红') return 'text-red-400'
  if (s === '排队中' || s === '待对冲') return 'text-yellow-400'
  if (EXEC_STATUSES.has(s)) return 'text-blue-400'
  return 'text-muted-foreground'
}

// ─── CoinHeaderRow ───

const CoinHeaderRow = memo(function CoinHeaderRow({
  group,
  isExpanded,
  compact,
  isMobile,
  isDelisting,
  isRisky,
  borrowDisplayUsdt,
  symbolStatus,
  marketInfo,
  throttleRate,
  onToggle,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
}: {
  group: SymbolGroup
  isExpanded: boolean
  compact?: boolean
  isMobile: boolean
  throttleRate?: number
  isDelisting?: boolean
  isRisky?: boolean
  borrowDisplayUsdt?: boolean
  symbolStatus?: string | null
  marketInfo?: MarketInfo
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
}) {
  const hasPos = group.positions.length > 0
  // 开仓点差 = spread_short = (spot_bid-fut_ask)/fut_ask×100 (%)，与交易引擎/规则口径一致
  const openPct = group.spread ? group.spread.spread_short : null
  const closePct = group.spread ? group.spread.spread_long : null
  const spreadFlash = useFlash(`${group.symbol}-ss`, openPct?.toFixed(4))

  const coinName = group.symbol
  const dh = group.durationHours
  const dhText = dh != null ? (dh > 24 ? `${Math.floor(dh / 24)}d${Math.floor(dh % 24)}h` : `${Math.floor(dh)}h`) : '-'

  const rule = group.ruleInfo
  const hasCustomRule = rule && rule.source === 'custom' && (rule.open_spread != null || rule.close_spread != null)

  return (
    <tr
      className={cn(
        'border-b border-border/30 hover:bg-accent/20 cursor-pointer transition-colors text-[11px]',
        hasPos ? 'bg-[#111118]' : 'bg-[#0d0d14]/50',
      )}
      onClick={() => { if (!compact) onToggle(group.symbol) }}
      onDoubleClick={() => onDoubleClick(group.symbol)}
      onContextMenu={(e) => onContextMenu(e, group.symbol)}
    >
      {/* expand toggle */}
      <td className="px-1.5 py-1 text-center text-muted-foreground w-5">
        {compact ? '·' : hasPos ? (isExpanded ? '▾' : '▸') : '·'}
      </td>
      {/* 币种 */}
      <td className={cn('px-1.5 py-1 font-medium whitespace-nowrap', isDelisting ? 'text-red-500' : 'text-foreground')}>
        {isRisky && <span className="text-red-500 mr-0.5" title="风险币种">&#9888;</span>}
        {coinName}
        {hasPos && (
          <span className="ml-1 text-[9px] text-muted-foreground">×{group.openCount}</span>
        )}
        {isMobile && hasPos && (
          <span className="ml-1 text-[9px] text-muted-foreground">{dhText}</span>
        )}
      </td>
      {/* 现-期 — 合约腿名义价值(USDT)；tooltip 给出张数 */}
      {!isMobile && (
        <td
          className="px-1 py-1 text-right tabular-nums font-mono text-[10px]"
          title={group.futQty != null ? `合约张数: ${formatNumber(group.futQty, 4)}　名义价值: ${formatNumber(group.futNotional ?? 0, 2)} USDT` : undefined}
        >
          {group.futNotional != null ? formatNumber(group.futNotional, 0) : '-'}
        </td>
      )}
      {/* 爆率 — liquidation pct */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.liquidationPct != null ? (
            <span className={group.liquidationPct > 80 ? 'text-negative' : group.liquidationPct > 50 ? 'text-yellow-400' : 'text-positive'}>
              {formatNumber(group.liquidationPct, 1)}%
            </span>
          ) : '-'}
        </td>
      )}
      {/* 最大借 — max borrowable (qty or USDT based on toggle) */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalMaxBorrow != null
            ? borrowDisplayUsdt
              ? formatNumber(group.totalMaxBorrow * (group.spread?.spot_bid ?? 0), 0)
              : formatNumber(group.totalMaxBorrow, 2)
            : '-'}
        </td>
      )}
      {/* 现币 — current borrowable */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalFree != null ? formatNumber(group.totalFree, 4) : '-'}
        </td>
      )}
      {/* 借币 */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalQty > 0 ? formatNumber(group.totalQty, 4) : '-'}
        </td>
      )}
      {/* 金额 */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalUsdt > 0 ? formatNumber(group.totalUsdt, 0) : '-'}
        </td>
      )}
      {/* 风险 — aggregated margin level */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.minMarginLevel != null ? (
            <span className={group.minMarginLevel > 2 ? 'text-positive' : group.minMarginLevel > 1.3 ? 'text-yellow-400' : 'text-negative'}>
              {formatNumber(group.minMarginLevel, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 保证金 — margin USDT free */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalMarginFree != null ? formatNumber(group.totalMarginFree, 0) : '-'}
        </td>
      )}
      {/* 可用 — futures available */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {group.totalFutAvail != null ? formatNumber(group.totalFutAvail, 0) : '-'}
        </td>
      )}
      {/* 润 — 已下沉到子账户明细，币种汇总行不显示 */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px] text-muted-foreground">-</td>
      )}
      {/* 开 — 开仓点差 % (spread_short) */}
      <td className={cn('px-1 py-1 text-right tabular-nums font-mono text-[10px]', spreadFlash)}>
        {openPct != null ? (
          <span className="text-positive">{formatNumber(openPct, 2)}</span>
        ) : '-'}
      </td>
      {/* 平 — 平仓点差 % (spread_long) */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {closePct != null ? (
            <span className="text-negative">{formatNumber(closePct, 2)}</span>
          ) : '-'}
        </td>
      )}
      {/* 资 — real-time funding rate (%) */}
      <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
        {marketInfo ? (
          <span className={marketInfo.funding_rate >= 0 ? 'text-positive' : 'text-negative'}>
            {(marketInfo.funding_rate * 100).toFixed(2)}
          </span>
        ) : '-'}
      </td>
      {/* 时 — funding interval hours */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px] text-muted-foreground">
          {marketInfo ? marketInfo.funding_interval : '-'}
        </td>
      )}
      {/* 限 — funding rate cap */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {marketInfo && marketInfo.funding_cap > 0 ? (
            <span className="text-amber-400">{(marketInfo.funding_cap * 100).toFixed(1)}</span>
          ) : '-'}
        </td>
      )}
      {/* 息 — daily interest rate */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
          {marketInfo && marketInfo.daily_interest > 0 ? (
            <span className="text-amber-400">{(marketInfo.daily_interest * 100).toFixed(4)}%</span>
          ) : '-'}
        </td>
      )}
      {/* 推/时 — push time */}
      {!isMobile && (
        <td className="px-1 py-1 text-right whitespace-nowrap text-[10px]">
          {group.pushTime ? (
            <span className="text-muted-foreground">{group.pushTime}</span>
          ) : group.isPushed ? (
            <span className="text-primary text-[9px]">已推</span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
      )}
      {/* 资倍 — 资息倍率 (signed: 负费率=成本) */}
      <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px]">
        {marketInfo && marketInfo.ratio !== 0 ? (
          <span className={marketInfo.ratio >= 0 ? 'text-positive' : 'text-negative'}>
            {formatNumber(marketInfo.ratio, 2)}
          </span>
        ) : '-'}
      </td>
      {/* 单 — custom rule indicator */}
      {!isMobile && (
        <td
          className="px-0.5 py-1 text-center text-[9px] whitespace-nowrap cursor-pointer hover:bg-accent/30"
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
      {/* 移 — allow_remove */}
      {!isMobile && (
        <td className="px-0.5 py-1 text-center text-[10px]">
          {rule ? (
            <span className={rule.allow_remove ? 'text-positive' : 'text-negative'}>●</span>
          ) : (
            <span className="text-positive">●</span>
          )}
        </td>
      )}
      {/* 还 — allow_repay */}
      {!isMobile && (
        <td className="px-0.5 py-1 text-center text-[10px]">
          {rule ? (
            <span className={rule.allow_repay ? 'text-positive' : 'text-negative'}>●</span>
          ) : (
            <span className="text-positive">●</span>
          )}
        </td>
      )}
      {/* 状态 — symbol operational status */}
      {!isMobile && (
        <td className="px-1 py-1 text-center whitespace-nowrap text-[10px]">
          {symbolStatus ? (
            <span className={statusColorCls(symbolStatus)}>{symbolStatus}</span>
          ) : '-'}
        </td>
      )}
      {/* 速率 — 当前限流余量下每币借币速率 (req/s)，全局值 */}
      {!isMobile && (
        <td className="px-1 py-1 text-right tabular-nums font-mono text-[10px] text-muted-foreground"
            title="当前限流余量下每币可借速率 (req/s)">
          {throttleRate && throttleRate > 0 ? `${throttleRate.toFixed(2)}/s` : '-'}
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
  onContextMenu: (e: React.MouseEvent, symbol: string, position: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
}) {
  return (
    <tr
      className="border-b border-border/10 hover:bg-accent/10 cursor-pointer text-[11px] bg-[#0c0c11]"
      onDoubleClick={() => onDoubleClick(pos.symbol, pos.sub_account_id)}
      onContextMenu={(e) => onContextMenu(e, pos.symbol, pos)}
    >
      <td className="px-1.5 py-0.5"></td>
      {/* 币种 → account note */}
      <td className="px-1.5 py-0.5 pl-4 text-muted-foreground whitespace-nowrap">
        ↳ {pos.account_note || `#${pos.sub_account_id}`}
        {isMobile && (
          <span className="ml-1 text-[9px]">{durationText(pos.opened_at)}</span>
        )}
      </td>
      {/* 现-期 — this account's futures notional (tooltip: 张数) */}
      {!isMobile && (() => {
        const qty = parseFloat(pos.futures_long_qty || '0')
        const price = spread?.fut_bid ?? 0
        const val = qty * price
        return (
          <td
            className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]"
            title={qty > 0 ? `合约张数: ${formatNumber(qty, 4)}　名义价值: ${formatNumber(val, 2)} USDT` : undefined}
          >
            {val > 0 ? formatNumber(val, 0) : '-'}
          </td>
        )
      })()}
      {/* 爆率 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance && balance.margin_level > 0 ? (() => {
            const pct = (1.1 / balance.margin_level) * 100
            return (
              <span className={pct > 80 ? 'text-negative' : pct > 50 ? 'text-yellow-400' : 'text-positive'}>
                {formatNumber(pct, 1)}%
              </span>
            )
          })() : '-'}
        </td>
      )}
      {/* 最大借 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance?.symbol_margin?.[pos.symbol]?.max_borrowable != null
            ? borrowDisplayUsdt
              ? formatNumber(balance.symbol_margin[pos.symbol].max_borrowable * (spread?.spot_bid ?? 0), 0)
              : formatNumber(balance.symbol_margin[pos.symbol].max_borrowable, 2)
            : '-'}
        </td>
      )}
      {/* 现币 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance?.symbol_margin?.[pos.symbol]?.free != null
            ? formatNumber(balance.symbol_margin[pos.symbol].free, 4)
            : '-'}
        </td>
      )}
      {/* 借币 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {formatNumber(pos.borrow_qty, 4)}
        </td>
      )}
      {/* 金额 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {pos.open_usdt_amount ? formatNumber(pos.open_usdt_amount) : '-'}
        </td>
      )}
      {/* 风险 — margin level */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance ? (
            <span className={balance.margin_level > 2 ? 'text-positive' : balance.margin_level > 1.3 ? 'text-yellow-400' : 'text-negative'}>
              {formatNumber(balance.margin_level, 2)}
            </span>
          ) : '-'}
        </td>
      )}
      {/* 保证金 — 杠杆账户净权益(USDT)，回退可用USDT */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance ? formatNumber(balance.margin_net_usdt ?? balance.margin_usdt_free, 0) : '-'}
        </td>
      )}
      {/* 可用 */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {balance ? formatNumber(balance.futures_available, 0) : '-'}
        </td>
      )}
      {/* 润 — 持仓净盈亏 (已实现+资金费-利息) */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {(() => {
            const profit = parseFloat(pos.realized_pnl || '0')
              + parseFloat(pos.cumulative_funding_fee || '0')
              - parseFloat(pos.cumulative_interest || '0')
            return <span className={pnlColor(profit)}>{formatNumber(profit, 2)}</span>
          })()}
        </td>
      )}
      {/* 开 — 开仓点差 % (spread_short) */}
      <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
        {spread ? (
          <span className="text-positive">{formatNumber(spread.spread_short, 2)}</span>
        ) : '-'}
      </td>
      {/* 平 — 平仓点差 % (spread_long) */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {spread ? (
            <span className="text-negative">{formatNumber(spread.spread_long, 2)}</span>
          ) : '-'}
        </td>
      )}
      {/* 资 — funding rate (%) */}
      <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
        {marketInfo ? (
          <span className={marketInfo.funding_rate >= 0 ? 'text-positive' : 'text-negative'}>
            {(marketInfo.funding_rate * 100).toFixed(2)}
          </span>
        ) : '-'}
      </td>
      {/* 时 — funding interval */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px] text-muted-foreground">
          {marketInfo ? marketInfo.funding_interval : '-'}
        </td>
      )}
      {/* 限 — funding cap */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {marketInfo && marketInfo.funding_cap > 0 ? (
            <span className="text-amber-400">{(marketInfo.funding_cap * 100).toFixed(1)}</span>
          ) : '-'}
        </td>
      )}
      {/* 息 — daily interest rate from market data */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
          {marketInfo && marketInfo.daily_interest > 0 ? (
            <span className="text-amber-400">{(marketInfo.daily_interest * 100).toFixed(4)}%</span>
          ) : '-'}
        </td>
      )}
      {/* 推/时 → duration or ban countdown */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-right whitespace-nowrap text-[10px]">
          {banRemaining != null && banRemaining > 0 ? (
            <span className="text-red-500 font-mono">{Math.floor(banRemaining / 60)}:{String(banRemaining % 60).padStart(2, '0')}</span>
          ) : (
            <span className="text-muted-foreground">{durationText(pos.opened_at)}</span>
          )}
        </td>
      )}
      {/* 资倍 — 资息倍率 (signed) */}
      <td className="px-1 py-0.5 text-right tabular-nums font-mono text-[10px]">
        {marketInfo && marketInfo.ratio !== 0 ? (
          <span className={marketInfo.ratio >= 0 ? 'text-positive' : 'text-negative'}>
            {formatNumber(marketInfo.ratio, 2)}
          </span>
        ) : '-'}
      </td>
      {/* 单 — empty for sub-account rows */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 移 — empty */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 还 — empty */}
      {!isMobile && <td className="px-0.5 py-0.5"></td>}
      {/* 状态 — operational status */}
      {!isMobile && (
        <td className="px-1 py-0.5 text-center whitespace-nowrap text-[10px]">
          {symbolStatus ? (
            <span className={statusColorCls(symbolStatus)}>{symbolStatus}</span>
          ) : '-'}
        </td>
      )}
      {/* 速率 — 仅币种汇总行显示，子账户行留空 */}
      {!isMobile && <td className="px-1 py-0.5"></td>}
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

export function OwlTreeTable({ positions, pushedSymbols, symbolRules, delistingSymbols, riskySymbols, throttleRate, onAction }: OwlTreeTableProps) {
  const spreads = useSpreadStore((s) => s.spreads)
  const balances = useBalanceStore((s) => s.balances)
  const bans = useBanStore((s) => s.bans)
  const symbolStatuses = useSymbolStatusStore((s) => s.statuses)
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

    const allSymbols = new Set([...bySymbol.keys(), ...pushedSet])
    const q = search.toUpperCase()
    const result: SymbolGroup[] = []

    for (const symbol of allSymbols) {
      if (q && !symbol.includes(q)) continue
      const sp = spreads.get(symbol)
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
      const pushTime = earliest && earliest < Infinity
        ? new Date(earliest).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        : null

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
            if (sm.max_borrowable > 0) { mb += sm.max_borrowable; hasMb = true }
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
        symbol, spread: sp, positions: pos,
        totalQty, totalUsdt, totalFunding, totalInterest, groupProfit,
        isPushed: pushedSet.has(symbol),
        openCount: pos.length,
        durationHours: dh,
        pushTime,
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
  }, [spreads, positions, search, pushedSet, showPositionsOnly, balanceMap, symbolRules])

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

  const handleMobileMenu = useCallback((e: React.MouseEvent, symbol: string, position?: Position) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setContextMenu({ x: rect.left, y: rect.bottom, symbol, position })
  }, [])

  const handleDoubleClick = useCallback((symbol: string, subAccountId?: number) => {
    onAction('set_rule', symbol, undefined, subAccountId ? { initialAccountId: subAccountId } : undefined)
  }, [onAction])

  useEffect(() => {
    const close = () => setContextMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  const expandAll = useCallback(() => {
    setExpanded(new Set(groups.filter(g => g.positions.length > 0).map(g => g.symbol)))
  }, [groups])

  const collapseAll = useCallback(() => {
    setExpanded(new Set())
  }, [])

  const posCount = groups.filter(g => g.positions.length > 0).length
  const totalUsdt = groups.reduce((s, g) => s + g.totalUsdt, 0)
  const totalFunding = groups.reduce((s, g) => s + g.totalFunding, 0)
  const totalInterest = groups.reduce((s, g) => s + g.totalInterest, 0)
  const totalProfit = totalFunding - totalInterest

  const colCount = isMobile ? 6 : 25

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
        <table className={cn('w-full', !isMobile && 'min-w-[1300px]')}>
          <thead className="sticky top-0 z-10">
            <tr className="bg-[#0d0d14] text-[10px] text-muted-foreground border-b border-border">
              <th className="px-1.5 py-1 text-left font-medium w-5"></th>
              <th className="px-1.5 py-1 text-left font-medium">币种</th>
              {!isMobile && <th className="px-1 py-1 text-right font-medium" title="合约腿名义价值 (合约张数 × 期货买价, USDT)。悬停单元格看张数">现-期</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">爆率</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">最大可借</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">现币</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">借币</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">借币金额</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">风险</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">保证金</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">可用</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">润</th>}
              <th className="px-1 py-1 text-right font-medium">开</th>
              {!isMobile && <th className="px-1 py-1 text-right font-medium">平</th>}
              <th className="px-1 py-1 text-right font-medium">资</th>
              {!isMobile && <th className="px-1 py-1 text-right font-medium">时</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">限</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">息</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">推/时</th>}
              <th className="px-1 py-1 text-right font-medium">资倍</th>
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">单</th>}
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">移</th>}
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">还</th>}
              {!isMobile && <th className="px-0.5 py-1 text-center font-medium">状态</th>}
              {!isMobile && <th className="px-1 py-1 text-right font-medium">速率</th>}
              {isMobile && <th className="px-0.5 py-1 w-7"></th>}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const isExp = !compact && expanded.has(g.symbol)
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
                  marketData={marketData}
                  throttleRate={throttleRate}
                  onToggle={toggle}
                  onContextMenu={handleContextMenu}
                  onDoubleClick={handleDoubleClick}
                  onMobileMenu={handleMobileMenu}
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
  marketData,
  throttleRate,
  onToggle,
  onContextMenu,
  onDoubleClick,
  onMobileMenu,
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
  marketData: Map<string, MarketInfo>
  throttleRate?: number
  onToggle: (symbol: string) => void
  onContextMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
  onDoubleClick: (symbol: string, subAccountId?: number) => void
  onMobileMenu: (e: React.MouseEvent, symbol: string, position?: Position) => void
}) {
  const headerStatus = useMemo(() => {
    const priority = ['借币停止', '借币红', '排队中', '借币中', '开仓中', '平仓中', '买回中', '还币中', '点差不符']
    for (const s of priority) {
      if (group.positions.some(p => symbolStatuses.get(`${p.sub_account_id}:${p.symbol}`) === s)) return s
    }
    return null
  }, [group.positions, symbolStatuses])

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
        throttleRate={throttleRate}
        onToggle={onToggle}
        onContextMenu={onContextMenu}
        onDoubleClick={onDoubleClick}
        onMobileMenu={onMobileMenu}
      />
      {isExpanded && group.positions.map((pos) => {
        const banKey = `${pos.sub_account_id}:${pos.symbol}`
        const banEntry = bans.get(banKey)
        const banRemaining = banEntry
          ? Math.max(0, banEntry.remaining - Math.floor((Date.now() - banEntry.updatedAt) / 1000))
          : undefined
        const posStatus = symbolStatuses.get(banKey) ?? null
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
            marketInfo={marketData.get(pos.symbol)}
            onContextMenu={onContextMenu}
            onDoubleClick={onDoubleClick}
            onMobileMenu={onMobileMenu}
          />
        )
      })}
    </>
  )
})
