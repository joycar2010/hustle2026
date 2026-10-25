const HEADER_STATUS_PRIORITY = [
  '借币待核对', '执行异常', '借币核对中', '借币停止', '借币红', '借币准备',
  '卖现货中', '合约开多中', '合约平仓中', '平仓中', '买回中', '还币中',
  '已借币待卖现货', '待还币', '已开仓',
  '保证金保护', '仓位已满', '并联满', '借币异常', '协调不可用',
  '点差不符', '无券', '还币暂停', '借币冷却', '移除冷却', '量不足',
  '行情陈旧', '行情异常', '禁借', '黑名单', '不可交易', '已完成',
]

export function dashboardStatus(status?: string | null): string | null {
  return dashboardStatusPresentation(status).label
}

export type DashboardStatusTone = 'normal' | 'waiting' | 'warning' | 'error'

export interface DashboardStatusPresentation {
  /** Three-state lifecycle phase retained for compact operator scanning. */
  label: string | null
  rawStatus: string | null
  tone: DashboardStatusTone
  /** Blocking/error reason that must be rendered visibly, not tooltip-only. */
  diagnosticLabel: string | null
}

const ERROR_STATUSES = new Set([
  '借币待核对', '借币停止', '借币红', '借币异常', '协调不可用', '行情异常',
  '禁借', '黑名单', '不可交易', '死币', '配置冲突', '执行异常',
])

const WARNING_STATUSES = new Set([
  '保证金保护', '仓位已满', '并联满', '无券', '还币暂停',
  '借币冷却', '移除冷却', '量不足', '行情陈旧', 'API限制',
  'E闸拒开', '库存预检',
])

const WAITING_OPEN_STATUSES = new Set([
  '等待开仓', '已借币待卖现货', '卖现货中', '合约开多中',
  'BORROWED', 'BORROWED_IDLE', 'HEDGING', 'SPOT_SOLD',
])

/**
 * The dashboard's borrow column is intentionally a three-state operator view:
 * running, spread not met, or borrowed and waiting to open. Detailed engine
 * and guard states stay in ``rawStatus`` and remain available in tooltips.
 */
function visibleBorrowStatus(status: string): string {
  if (status === '点差不符') return '点差不符'
  if (WAITING_OPEN_STATUSES.has(status)) return '等待开仓'
  return '运行中'
}

export function dashboardStatusPresentation(status?: string | null): DashboardStatusPresentation {
  if (!status) {
    return { label: null, rawStatus: null, tone: 'normal', diagnosticLabel: null }
  }
  const label = visibleBorrowStatus(status)
  if (ERROR_STATUSES.has(status)) {
    return {
      label,
      rawStatus: status,
      tone: 'error',
      diagnosticLabel: status !== label ? status : null,
    }
  }
  if (WARNING_STATUSES.has(status)) {
    return {
      label,
      rawStatus: status,
      tone: 'warning',
      diagnosticLabel: status !== label ? status : null,
    }
  }
  if (status === '点差不符' || status === '借币核对中') {
    return { label, rawStatus: status, tone: 'waiting', diagnosticLabel: null }
  }
  return { label, rawStatus: status, tone: 'normal', diagnosticLabel: null }
}

export function isBorrowExecutionStatus(status?: string | null): boolean {
  return status === '借币中'
}

const POSITION_FALLBACK_LABELS: Record<string, string> = {
  PUSHED: '运行中',
  PENDING_BORROW: '运行中',
  BORROW_SUBMITTING: '运行中',
  BORROW_OUTCOME_UNKNOWN: '运行中',
  BORROWED: '等待开仓',
  BORROWED_IDLE: '等待开仓',
  HEDGING: '等待开仓',
  SPOT_SOLD: '等待开仓',
  OPEN: '运行中',
  CLOSING: '运行中',
  CLOSING_FUTURES: '运行中',
  FUTURES_CLOSED: '运行中',
  CLOSING_SPOT: '运行中',
  SPOT_BOUGHT: '运行中',
  PENDING_REPAY: '运行中',
  REPAYING: '运行中',
  CLOSED: '运行中',
  FAILED: '运行中',
}

export function positionFallbackLabel(status?: string | null): string {
  if (!status) return '-'
  return POSITION_FALLBACK_LABELS[status] ?? visibleBorrowStatus(status)
}

/** Resolve one row without allowing a sibling bite's symbol status to win. */
export function positionRowStatus(
  positionStatus?: string | null,
  symbolDecisionStatus?: string | null,
): string | null {
  if (positionStatus === 'PUSHED') return symbolDecisionStatus || null
  if (!positionStatus) return null
  return POSITION_FALLBACK_LABELS[positionStatus] ?? visibleBorrowStatus(positionStatus)
}

function selectHeaderStatus(statuses: Array<string | undefined>): string | null {
  // An unresolved exchange outcome requires operator attention and takes
  // precedence even when a sibling account is currently submitting.
  if (statuses.includes('借币待核对')) return '借币待核对'
  // A real request in any account must remain visible after the symbol is
  // collapsed, even if a sibling account is stopped or waiting.
  if (statuses.some(status => isBorrowExecutionStatus(status))) return '借币中'
  for (const status of HEADER_STATUS_PRIORITY) {
    if (statuses.includes(status)) return status
  }
  return statuses.find((status): status is string => Boolean(status)) ?? null
}

export function aggregateSymbolHeaderStatus(
  positionStatuses: Array<string | undefined>,
  pushedDecisionStatuses: Array<string | undefined> = [],
): string | null {
  // A synthetic PUSHED decision belongs to an idle account. It must never
  // replace the lifecycle of a real position in the collapsed symbol row.
  return selectHeaderStatus(positionStatuses) ?? selectHeaderStatus(pushedDecisionStatuses)
}
