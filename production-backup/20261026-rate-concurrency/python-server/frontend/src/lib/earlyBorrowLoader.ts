import { EARLY_BORROW_REQUEST_TIMEOUT_MS } from '@/api/earlyBorrow'
import type {
  EarlyBorrowCandidate,
  EarlyBorrowCase,
  EarlyBorrowStatus,
  EarlyBorrowWarning,
} from '@/api/earlyBorrow'

export { EARLY_BORROW_REQUEST_TIMEOUT_MS }

export type EarlyBorrowResource = 'status' | 'candidates' | 'cases'
export type EarlyBorrowLoadState = 'loading' | 'ready' | 'error'

export interface EarlyBorrowRequests {
  status: (signal: AbortSignal) => Promise<EarlyBorrowStatus>
  candidates: (signal: AbortSignal) => Promise<{
    items: EarlyBorrowCandidate[]
    warnings: EarlyBorrowWarning[]
    read_only: true
  }>
  cases: (signal: AbortSignal) => Promise<{
    items: EarlyBorrowCase[]
    read_only: true
  }>
}

interface EarlyBorrowCallbacks {
  onState: (resource: EarlyBorrowResource, state: EarlyBorrowLoadState) => void
  onStatus: (value: EarlyBorrowStatus) => void
  onCandidates: (value: Awaited<ReturnType<EarlyBorrowRequests['candidates']>>) => void
  onCases: (value: Awaited<ReturnType<EarlyBorrowRequests['cases']>>) => void
}

interface EarlyBorrowLoadOptions {
  signal?: AbortSignal
  timeoutMs?: number
}

export class EarlyBorrowTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`EarlyBorrow request timed out after ${timeoutMs}ms`)
    this.name = 'EarlyBorrowTimeoutError'
  }
}

class EarlyBorrowAbortError extends Error {
  constructor() {
    super('EarlyBorrow request aborted')
    this.name = 'EarlyBorrowAbortError'
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof EarlyBorrowAbortError
}

export function withEarlyBorrowTimeout<T>(
  request: (signal: AbortSignal) => Promise<T>,
  options: EarlyBorrowLoadOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? EARLY_BORROW_REQUEST_TIMEOUT_MS

  return new Promise<T>((resolve, reject) => {
    const controller = new AbortController()
    let settled = false

    const cleanup = () => {
      clearTimeout(timer)
      options.signal?.removeEventListener('abort', onParentAbort)
    }
    const rejectOnce = (error: unknown) => {
      if (settled) return
      settled = true
      cleanup()
      controller.abort()
      reject(error)
    }
    const onParentAbort = () => rejectOnce(new EarlyBorrowAbortError())
    const timer = setTimeout(() => rejectOnce(new EarlyBorrowTimeoutError(timeoutMs)), timeoutMs)

    if (options.signal?.aborted) {
      onParentAbort()
      return
    }

    options.signal?.addEventListener('abort', onParentAbort, { once: true })

    Promise.resolve()
      .then(() => request(controller.signal))
      .then(
        (value) => {
          if (settled) return
          settled = true
          cleanup()
          resolve(value)
        },
        (error) => {
          if (settled) return
          settled = true
          cleanup()
          reject(error)
        },
      )
  })
}

export function loadEarlyBorrowResources(
  requests: EarlyBorrowRequests,
  callbacks: EarlyBorrowCallbacks,
  options: EarlyBorrowLoadOptions = {},
): Promise<void> {
  const loadOne = async <T>(
    resource: EarlyBorrowResource,
    request: (signal: AbortSignal) => Promise<T>,
    onValue: (value: T) => void,
  ) => {
    callbacks.onState(resource, 'loading')
    try {
      const value = await withEarlyBorrowTimeout(request, options)
      onValue(value)
      callbacks.onState(resource, 'ready')
    } catch (error) {
      if (!isAbortError(error)) callbacks.onState(resource, 'error')
    }
  }

  return Promise.all([
    loadOne('status', requests.status, callbacks.onStatus),
    loadOne('candidates', requests.candidates, callbacks.onCandidates),
    loadOne('cases', requests.cases, callbacks.onCases),
  ]).then(() => undefined)
}
