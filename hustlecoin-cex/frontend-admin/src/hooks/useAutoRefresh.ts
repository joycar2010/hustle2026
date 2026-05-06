import { useEffect, useRef } from 'react'

export function useAutoRefresh(fn: () => Promise<void> | void, intervalMs: number) {
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    let backoff = 0
    let timeoutId: ReturnType<typeof setTimeout>
    let cancelled = false

    const tick = async () => {
      try {
        await fnRef.current()
        backoff = 0
      } catch {
        backoff = Math.min(backoff + 1, 5)
      }
      if (!cancelled) {
        const delay = intervalMs * Math.pow(2, backoff)
        timeoutId = setTimeout(tick, delay)
      }
    }

    tick()
    return () => { cancelled = true; clearTimeout(timeoutId) }
  }, [intervalMs])
}
