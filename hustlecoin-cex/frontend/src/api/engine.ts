import client from './client'

export async function getDashboard() {
  const { data } = await client.get('/api/engine/dashboard')
  return data
}

export async function getPositions(status?: string, signal?: AbortSignal) {
  const params = status ? { status } : {}
  const { data } = await client.get('/api/engine/positions', { params, signal })
  return data
}

export async function getPositionsSummary() {
  const { data } = await client.get('/api/engine/positions/summary')
  return data
}

export async function getPositionsHistory(params?: Record<string, string>) {
  const { data } = await client.get('/api/engine/positions/history', { params })
  return data
}

export async function getFundingFees() {
  const { data } = await client.get('/api/engine/funding-fees')
  return data
}

export async function getWorkersStatus() {
  const { data } = await client.get('/api/engine/workers/status')
  return data
}

export async function startAllWorkers() {
  const { data } = await client.post('/api/engine/workers/start')
  return data
}

export async function stopAllWorkers() {
  const { data } = await client.post('/api/engine/workers/stop')
  return data
}

export async function startWorker(id: number) {
  const { data } = await client.post(`/api/engine/workers/${id}/start`)
  return data
}

export async function stopWorker(id: number) {
  const { data } = await client.post(`/api/engine/workers/${id}/stop`)
  return data
}

export async function restartWorker(id: number) {
  const { data } = await client.post(`/api/engine/workers/${id}/restart`)
  return data
}

export interface TradeLogEntry {
  id: number
  position_id: number | null
  action: string
  symbol: string
  side: string | null
  quantity: string | null
  price: string | null
  order_id: string | null
  status: string
  error_message: string | null
  latency_ms: number | null
  created_at: string
}

export async function getTradeLogs(params?: Record<string, string>) {
  const { data } = await client.get('/api/engine/trade-logs', { params })
  return data as TradeLogEntry[]
}

export async function getAccountBalance(id: number) {
  const { data } = await client.get(`/api/engine/accounts/${id}/balance`)
  return data
}

export async function getMaxBorrowable(id: number, symbol: string) {
  const { data } = await client.get(`/api/engine/accounts/${id}/max-borrowable/${symbol}`)
  return data
}

export interface TailPosition {
  id: number; symbol: string; sub_account_id: number
  open_usdt_amount: string; borrow_qty: string; opened_at: string
}
export async function listTailPositions(maxUsdt = 10): Promise<TailPosition[]> {
  const { data } = await client.get('/api/engine/positions/tail', { params: { max_usdt: maxUsdt } })
  return data
}
export async function cleanupTailPositions(maxUsdtAmount = 10) {
  const { data } = await client.post('/api/engine/positions/tail/cleanup', { max_usdt_amount: maxUsdtAmount })
  return data
}

export async function getLoanHistory(id: number, type: 'BORROW' | 'REPAY' | 'INTEREST', asset?: string, size = 30): Promise<{ type: string; rows: Record<string, unknown>[]; total: number }> {
  const { data } = await client.get(`/api/engine/accounts/${id}/loan-history`, { params: { type, asset, size } })
  return data
}

export async function manualTransfer(id: number, body: Record<string, unknown>) {
  const { data } = await client.post(`/api/engine/accounts/${id}/transfer`, body)
  return data
}

export async function crossAccountTransfer(id: number, body: Record<string, unknown>) {
  const { data } = await client.post(`/api/engine/accounts/${id}/transfer-cross`, body)
  return data
}

export async function getPushedSymbols(): Promise<{ pushed_symbols: string[]; pushed_at?: Record<string, number> }> {
  const { data } = await client.get('/api/engine/pushed-symbols')
  return data
}

export async function pushSymbol(symbol: string) {
  const { data } = await client.post(`/api/engine/push-symbol/${symbol}`)
  return data
}

export async function removePushedSymbol(symbol: string) {
  const { data } = await client.delete(`/api/engine/push-symbol/${symbol}`)
  return data
}

export async function partialRepay(subAccountId: number, symbol: string, amount: number) {
  const { data } = await client.post('/api/engine/partial-repay', {
    sub_account_id: subAccountId,
    symbol,
    amount,
  })
  return data
}

export async function manualOpen(subAccountId: number, symbol: string, orderAmount?: number) {
  const { data } = await client.post('/api/engine/manual-open', {
    sub_account_id: subAccountId,
    symbol,
    order_amount: orderAmount ?? null,
  })
  return data
}

export async function manualClose(positionId: number) {
  const { data } = await client.post('/api/engine/manual-close', {
    position_id: positionId,
  })
  return data
}

export async function manualHedge(positionId: number) {
  const { data } = await client.post('/api/engine/manual-hedge', { position_id: positionId })
  return data
}

export async function manualRepay(positionId: number) {
  const { data } = await client.post('/api/engine/manual-repay', { position_id: positionId })
  return data
}

export interface WorkerHealth {
  scope: string
  status: string
  last_heartbeat: string | null
  heartbeat_stale: boolean
  active_positions: number
  total_cycles: number
  error_message: string | null
}

export interface StuckPosition {
  id: number
  symbol: string
  sub_account_id: number
  status: string
  stuck_minutes: number
  error_message: string | null
}

export interface APIMetrics {
  total_calls: number
  total_errors: number
  rate_limited: number
  error_rate: number
  last_error_ago_sec: number | null
  last_error_msg: string | null
  last_success_ago_sec: number | null
}

export interface EngineHealth {
  status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY'
  engine_status: string
  workers: WorkerHealth[]
  stuck_positions: StuckPosition[]
  open_positions: number
  api_metrics: Record<string, APIMetrics>
  spread_count: number
  uptime_sec?: number | null
  used_weight_1m?: number
  weight_limit?: number
  weight_age_sec?: number | null
  uid_used_1m?: number
  uid_limit?: number
  throttle_rate?: number
  agg_borrow_rate?: number
  single_borrow_rate?: number
  account_borrow_rates?: Record<string, number>   // 逐子账户可借速率 {sub_account_id: req/s}
}

export async function getEngineHealth(signal?: AbortSignal): Promise<EngineHealth> {
  const { data } = await client.get('/api/engine/health', { signal })
  return data
}
