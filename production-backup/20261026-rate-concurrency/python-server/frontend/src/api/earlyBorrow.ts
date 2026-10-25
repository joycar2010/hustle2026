import client from './client'

export const EARLY_BORROW_REQUEST_TIMEOUT_MS = 5_000

const EARLY_BORROW_GET_CONFIG = {
  timeout: EARLY_BORROW_REQUEST_TIMEOUT_MS,
  __retryMax: 0,
  __silent: true,
} as const

export interface EarlyBorrowConfig {
  enabled: boolean
  sample_interval_sec: number
  metrics_interval_sec: number
  lookback_hours: number
  warning_spread_pct: number
  candidate_spread_pct: number
  trigger_spread_pct: number
  open_spread_pct: number
  open_spread_buffer_pct: number
  effective_candidate_spread_pct: number
  similarity_threshold: number
  notification_cooldown_sec: number
  retention_days: number
  read_only: true
}

export interface EarlyBorrowCandidate {
  id: number
  symbol: string
  detected_at: string | null
  current_spread: number
  similarity_score: number
  estimated_hit_rate: number | null
  matched_case_count: number
  evidence_case_ids?: number[]
  case_id: number | null
  feature_snapshot?: Record<string, unknown>
  status: 'suggested' | 'dismissed' | 'expired' | string
  notified_at: string | null
  expires_at: string | null
  note: string
}

export interface EarlyBorrowWarning {
  id: string
  symbol: string
  detected_at: string | null
  current_spread: number | null
  status: 'warning'
  expires_at: string | null
  note: string
  read_only: true
}

export interface EarlyBorrowCase {
  id: number
  symbol: string
  trigger_at: string | null
  trigger_spread: number
  window_start: string | null
  window_end: string | null
  sample_count: number
  feature_summary?: Record<string, unknown>
  status: 'ready' | 'warming' | string
}

export interface EarlyBorrowStatus {
  running: boolean
  enabled: boolean
  state: string
  universe_size: number
  last_tick_at: string | null
  last_feature_at: string | null
  latest_tick_at: string | null
  latest_feature_at: string | null
  last_error: string | null
  suggested_count: number
  case_count: number
  ready_case_count: number
  tick_count: number
  feature_count: number
  config: EarlyBorrowConfig
  read_only: true
}

export async function getEarlyBorrowStatus(signal?: AbortSignal): Promise<EarlyBorrowStatus> {
  const { data } = await client.get('/api/early-borrow/status', { ...EARLY_BORROW_GET_CONFIG, signal })
  return data
}

export async function getEarlyBorrowCandidates(
  limit = 100,
  signal?: AbortSignal,
  status: 'suggested' | 'dismissed' | 'expired' | 'recent' | 'all' = 'recent',
  compact = false,
): Promise<{ items: EarlyBorrowCandidate[]; warnings: EarlyBorrowWarning[]; read_only: true }> {
  const { data } = await client.get('/api/early-borrow/candidates', {
    params: { limit, status, compact },
    signal,
    ...EARLY_BORROW_GET_CONFIG,
  })
  return { items: data.items || [], warnings: data.warnings || [], read_only: true }
}

export async function getEarlyBorrowCases(
  limit = 20,
  signal?: AbortSignal,
  compact = false,
): Promise<{ items: EarlyBorrowCase[]; read_only: true }> {
  const { data } = await client.get('/api/early-borrow/cases', {
    params: { limit, compact },
    signal,
    ...EARLY_BORROW_GET_CONFIG,
  })
  return data
}

export async function dismissEarlyBorrowCandidate(candidateId: number) {
  const { data } = await client.post(`/api/early-borrow/candidates/${candidateId}/dismiss`, undefined, { __silent: true })
  return data as { ok: boolean; id: number; status: string }
}
