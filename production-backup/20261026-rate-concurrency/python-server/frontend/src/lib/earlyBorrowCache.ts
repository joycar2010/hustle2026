import {
  getEarlyBorrowCandidates,
  getEarlyBorrowCases,
  getEarlyBorrowStatus,
  type EarlyBorrowCandidate,
  type EarlyBorrowCase,
  type EarlyBorrowStatus,
  type EarlyBorrowWarning,
} from '@/api/earlyBorrow'

/** Keep monitor data warm for one modal reopen without persisting user data. */
export const EARLY_BORROW_CACHE_TTL_MS = 15_000

export type EarlyBorrowCandidatesResponse = Awaited<ReturnType<typeof getEarlyBorrowCandidates>>
export type EarlyBorrowCasesResponse = Awaited<ReturnType<typeof getEarlyBorrowCases>>
export type EarlyBorrowCacheResource = 'status' | 'candidates' | 'cases'
export type EarlyBorrowCacheErrors = Partial<Record<EarlyBorrowCacheResource, unknown>>

export interface EarlyBorrowSnapshot {
  status: EarlyBorrowStatus | null
  candidates: EarlyBorrowCandidatesResponse | null
  cases: EarlyBorrowCasesResponse | null
  fetchedAt: number
}

export interface EarlyBorrowResourceResult {
  resource: EarlyBorrowCacheResource
  value: unknown
  error?: unknown
}

export interface EarlyBorrowCacheResult {
  snapshot: EarlyBorrowSnapshot
  errors: EarlyBorrowCacheErrors
}

interface CacheEntry {
  subject: string
  values: Partial<Record<EarlyBorrowCacheResource, unknown>>
  fetchedAt: Partial<Record<EarlyBorrowCacheResource, number>>
}

const cacheEntries = new Map<string, CacheEntry>()

/**
 * A request can be observed by more than one component (the monitor tab and
 * its idle warm-up commonly overlap).  Keep one controller for the shared
 * network operation and abort it only after the last observer goes away.
 */
interface PendingRequest {
  promise: Promise<EarlyBorrowResourceResult>
  controller: AbortController
  observers: number
  settled: boolean
}

const inFlight = new Map<string, Map<EarlyBorrowCacheResource, PendingRequest>>()

function authSubject(): string {
  if (typeof localStorage === 'undefined') return ''
  let token = ''
  try {
    token = localStorage.getItem('cex_jwt_token') || ''
  } catch {
    return ''
  }
  if (!token) return ''
  try {
    const encoded = token.split('.')[1]
    if (!encoded) return token
    const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded)) as Record<string, unknown>
    const subject = payload.user_id ?? payload.sub ?? payload.username
    return subject == null ? token : String(subject)
  } catch {
    // Keep malformed tokens isolated as well; the API will report auth failure.
    return token
  }
}

function currentEntry(subject = authSubject()): CacheEntry | null {
  return subject ? cacheEntries.get(subject) || null : null
}

function isFresh(resource: EarlyBorrowCacheResource, entry: CacheEntry | null, now = Date.now()): boolean {
  const timestamp = entry?.fetchedAt[resource]
  return timestamp != null && now - timestamp <= EARLY_BORROW_CACHE_TTL_MS
}

function snapshotFor(entry: CacheEntry | null): EarlyBorrowSnapshot | null {
  if (!entry) return null
  const timestamps = (['status', 'candidates', 'cases'] as EarlyBorrowCacheResource[])
    .map((resource) => entry.fetchedAt[resource])
    .filter((value): value is number => value != null)
  return {
    status: (entry.values.status as EarlyBorrowStatus | undefined) || null,
    candidates: (entry.values.candidates as EarlyBorrowCandidatesResponse | undefined) || null,
    cases: (entry.values.cases as EarlyBorrowCasesResponse | undefined) || null,
    // The oldest resource controls snapshot freshness. This prevents a modal
    // from treating a newly fetched status plus an old candidate list as warm.
    fetchedAt: timestamps.length ? Math.min(...timestamps) : 0,
  }
}

export function getEarlyBorrowCache(): EarlyBorrowSnapshot | null {
  return snapshotFor(currentEntry())
}

export function isEarlyBorrowCacheFresh(maxAgeMs = EARLY_BORROW_CACHE_TTL_MS): boolean {
  const subject = authSubject()
  const entry = currentEntry(subject)
  if (!entry) return false
  const now = Date.now()
  const maxAge = Math.max(0, maxAgeMs)
  return (['status', 'candidates', 'cases'] as EarlyBorrowCacheResource[]).every((resource) => {
    const value = entry.values[resource]
    const timestamp = entry.fetchedAt[resource]
    return value != null && timestamp != null && now - timestamp <= maxAge
  })
}

function abortError(): Error {
  const error = new Error('Early-borrow request aborted')
  error.name = 'AbortError'
  return error
}

/** Stop one component waiting without cancelling a request shared by others. */
function withSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise
  if (signal.aborted) return Promise.reject(abortError())
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      cleanup()
      reject(abortError())
    }
    const cleanup = () => signal.removeEventListener('abort', onAbort)
    signal.addEventListener('abort', onAbort, { once: true })
    promise.then(
      (value) => { cleanup(); resolve(value) },
      (error) => { cleanup(); reject(error) },
    )
  })
}

function requestResource(resource: EarlyBorrowCacheResource, signal: AbortSignal): Promise<unknown> {
  switch (resource) {
    case 'status': return getEarlyBorrowStatus(signal)
    case 'candidates': return getEarlyBorrowCandidates(100, signal, 'recent', true)
    case 'cases': return getEarlyBorrowCases(8, signal, true)
  }
}

function releaseObserver(
  subject: string,
  resource: EarlyBorrowCacheResource,
  pending: PendingRequest,
  requestsForSubject: Map<EarlyBorrowCacheResource, PendingRequest>,
): void {
  if (pending.observers > 0) pending.observers -= 1
  // Do not cancel a request that another component still awaits.  The map
  // identity check prevents an old request from aborting a newer one after a
  // fast force-refresh replaced it.
  if (
    pending.observers === 0 &&
    !pending.settled &&
    requestsForSubject.get(resource) === pending
  ) {
    pending.controller.abort()
  }
  if (requestsForSubject.size === 0 && inFlight.get(subject) === requestsForSubject) {
    inFlight.delete(subject)
  }
}

function observePending(
  subject: string,
  resource: EarlyBorrowCacheResource,
  pending: PendingRequest,
  requestsForSubject: Map<EarlyBorrowCacheResource, PendingRequest>,
  signal?: AbortSignal,
): Promise<EarlyBorrowResourceResult> {
  pending.observers += 1
  // `finally` runs for both a normal response and the observer's own abort,
  // ensuring the shared controller is released exactly once per observer.
  return withSignal(pending.promise, signal).finally(() => {
    releaseObserver(subject, resource, pending, requestsForSubject)
  })
}

/** Load one resource with per-user, per-resource in-flight deduplication. */
export function loadEarlyBorrowResource(
  resource: EarlyBorrowCacheResource,
  options: { force?: boolean; signal?: AbortSignal } = {},
): Promise<EarlyBorrowResourceResult> {
  const subject = authSubject()
  if (!subject) return Promise.reject(new Error('Not authenticated'))
  if (options.signal?.aborted) return Promise.reject(abortError())
  const entry = currentEntry(subject)
  const cached = entry?.values[resource] ?? null
  if (!options.force && cached != null && isFresh(resource, entry)) {
    return withSignal(Promise.resolve({ resource, value: cached }), options.signal)
  }

  let subjectRequests = inFlight.get(subject)
  if (!subjectRequests) {
    subjectRequests = new Map()
    inFlight.set(subject, subjectRequests)
  }
  const pending = subjectRequests.get(resource)
  // A request whose last observer aborted may still be unwinding through
  // Axios. Do not attach a new caller to that already-cancelled operation.
  if (pending && !pending.controller.signal.aborted) {
    return observePending(subject, resource, pending, subjectRequests, options.signal)
  }
  if (pending) subjectRequests.delete(resource)

  const controller = new AbortController()
  const nextPending = {} as PendingRequest
  nextPending.controller = controller
  nextPending.observers = 0
  nextPending.settled = false
  nextPending.promise = Promise.resolve()
    .then(() => requestResource(resource, controller.signal))
    .then((value) => {
      const next: CacheEntry = cacheEntries.get(subject)
        ? cacheEntries.get(subject) as CacheEntry
        : { subject, values: {}, fetchedAt: {} }
      next.values[resource] = value
      next.fetchedAt[resource] = Date.now()
      cacheEntries.set(subject, next)
      return { resource, value }
    })
    .catch((error: unknown) => ({
      resource,
      // Keep a last-good value available while exposing the error to the UI.
      value: cached,
      error,
    }))
    .finally(() => {
      nextPending.settled = true
      if (subjectRequests?.get(resource) === nextPending) subjectRequests.delete(resource)
      if (subjectRequests?.size === 0 && inFlight.get(subject) === subjectRequests) {
        inFlight.delete(subject)
      }
    })
  subjectRequests.set(resource, nextPending)
  return observePending(subject, resource, nextPending, subjectRequests, options.signal)
}

/**
 * Start all monitor reads concurrently. `onResource` fires as each response
 * settles, so a slow status/cases endpoint can never hold back the candidate
 * table. Concurrent callers share each resource request.
 */
export function loadEarlyBorrowCache(options: {
  force?: boolean
  signal?: AbortSignal
  onResource?: (result: EarlyBorrowResourceResult) => void
} = {}): Promise<EarlyBorrowCacheResult> {
  const subject = authSubject()
  if (!subject) return Promise.reject(new Error('Not authenticated'))
  if (options.signal?.aborted) return Promise.reject(abortError())
  const resources: EarlyBorrowCacheResource[] = ['status', 'candidates', 'cases']
  const requests = resources.map((resource) => loadEarlyBorrowResource(resource, {
    force: options.force,
    // Forward the parent lifecycle signal to each shared observer. The
    // observer accounting above keeps this from cancelling siblings that are
    // still using the same in-flight request.
    signal: options.signal,
  }).then((result) => {
    options.onResource?.(result)
    return result
  }))
  const complete = Promise.all(requests).then((results) => {
    const errors: EarlyBorrowCacheErrors = {}
    for (const result of results) {
      if (result.error) errors[result.resource] = result.error
    }
    return {
      snapshot: snapshotFor(currentEntry(subject)) || { status: null, candidates: null, cases: null, fetchedAt: 0 },
      errors,
    }
  })
  return withSignal(complete, options.signal)
}

/** Best-effort idle warm-up used by the monitor page. */
export function primeEarlyBorrowCache(): Promise<EarlyBorrowCacheResult | null> {
  return loadEarlyBorrowCache().catch(() => null)
}

// Re-export response types for components that only depend on the cache API.
export type { EarlyBorrowCandidate, EarlyBorrowCase, EarlyBorrowStatus, EarlyBorrowWarning }
