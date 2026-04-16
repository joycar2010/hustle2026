import api from '@/services/api.js'
import dayjs from 'dayjs'

/**
 * Shared PnL data fetching utility for www frontend.
 * All pages use /api/v1/pnl/daily then aggregate client-side.
 */
export async function fetchDailyPnl(startDate, endDate) {
  const r = await api.get('/api/v1/pnl/daily', {
    params: { start_date: startDate, end_date: endDate, platform: 'all' }
  })
  return r.data // { daily_pnl: [...], summary: {...} }
}

/** Aggregate daily data into weekly buckets */
export function aggregateWeekly(dailyList) {
  const weeks = {}
  for (const d of dailyList) {
    const weekStart = dayjs(d.date).startOf('week').format('YYYY-MM-DD')
    if (!weeks[weekStart]) weeks[weekStart] = { week: weekStart, net_pnl: 0, trade_count: 0, days: 0 }
    weeks[weekStart].net_pnl += d.net_pnl
    weeks[weekStart].trade_count += d.trade_count
    weeks[weekStart].days++
  }
  return Object.values(weeks).sort((a, b) => a.week.localeCompare(b.week))
}

/** Aggregate daily data into monthly buckets */
export function aggregateMonthly(dailyList) {
  const months = {}
  for (const d of dailyList) {
    const month = d.date.substring(0, 7) // YYYY-MM
    if (!months[month]) months[month] = { month, net_pnl: 0, trade_count: 0, days: 0 }
    months[month].net_pnl += d.net_pnl
    months[month].trade_count += d.trade_count
    months[month].days++
  }
  return Object.values(months).sort((a, b) => a.month.localeCompare(b.month))
}

/** Format number with sign and 2 decimal places */
export function fmtPnl(v) {
  if (v == null || isNaN(v)) return '--'
  const n = parseFloat(v)
  return (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtNum(v) {
  if (v == null || isNaN(v)) return '--'
  return parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function pnlColor(v) {
  if (v == null || isNaN(v)) return ''
  return parseFloat(v) >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'
}
