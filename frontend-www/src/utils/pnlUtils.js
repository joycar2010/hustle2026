import api from '@/services/api.js'
import dayjs from 'dayjs'

// Module-level cache shared across all views (survives route changes)
// key -> { data, expireAt }
const _cache = new Map()
const _CACHE_TTL_MS = 60_000  // 60s

// In-flight dedup: key -> Promise (prevents parallel identical requests)
const _inflight = new Map()

let _wsInstance = null
export function setWsInstance(wsInst) { _wsInstance = wsInst }

function _cacheKey(prefix, ...parts) {
  return prefix + ':' + parts.join(':')
}

function _cacheGet(key) {
  const entry = _cache.get(key)
  if (entry && Date.now() < entry.expireAt) return entry.data
  _cache.delete(key)
  return null
}

function _cacheSet(key, data) {
  _cache.set(key, { data, expireAt: Date.now() + _CACHE_TTL_MS })
}

export function clearPnlCache() { _cache.clear() }

export async function fetchDailyPnl(startDate, endDate) {
  const key = _cacheKey('pnl', startDate, endDate)
  const cached = _cacheGet(key)
  if (cached) return cached

  // Dedup concurrent calls with same params
  if (_inflight.has(key)) return _inflight.get(key)

  const promise = api.get('/api/v1/pnl/daily', {
    params: { start_date: startDate, end_date: endDate, platform: 'all' }
  }).then(r => {
    _cacheSet(key, r.data)
    _inflight.delete(key)
    return r.data
  }).catch(e => {
    _inflight.delete(key)
    throw e
  })

  _inflight.set(key, promise)
  return promise
}

export async function fetchFundFlow(days) {
  const d = days || 30
  const key = _cacheKey('ff', d)
  const cached = _cacheGet(key)
  if (cached) return cached

  if (_inflight.has(key)) return _inflight.get(key)

  const promise = api.get('/api/v1/accounts/me/fund-flow', {
    params: { days: d }
  }).then(r => {
    _cacheSet(key, r.data)
    _inflight.delete(key)
    return r.data
  }).catch(e => {
    _inflight.delete(key)
    throw e
  })

  _inflight.set(key, promise)
  return promise
}

export function aggregateWeekly(dailyList) {
  const weeks = {}
  for (const d of dailyList) {
    const _dd = dayjs(d.date)
    const weekStart = _dd.subtract((_dd.day() + 6) % 7, 'day').format('YYYY-MM-DD')  // 周一起
    if (!weeks[weekStart]) weeks[weekStart] = { week: weekStart, net_pnl: 0, trade_count: 0, days: 0 }
    weeks[weekStart].net_pnl += d.net_pnl
    weeks[weekStart].trade_count += d.trade_count
    weeks[weekStart].days++
  }
  return Object.values(weeks).sort((a, b) => a.week.localeCompare(b.week))
}

export function aggregateMonthly(dailyList) {
  const months = {}
  for (const d of dailyList) {
    const month = d.date.substring(0, 7)
    if (!months[month]) months[month] = { month, net_pnl: 0, trade_count: 0, days: 0 }
    months[month].net_pnl += d.net_pnl
    months[month].trade_count += d.trade_count
    months[month].days++
  }
  return Object.values(months).sort((a, b) => a.month.localeCompare(b.month))
}

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
