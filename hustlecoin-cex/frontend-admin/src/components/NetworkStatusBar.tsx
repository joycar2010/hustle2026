import { useState, useEffect } from 'react'

export function NetworkStatusBar() {
  const [online, setOnline] = useState(navigator.onLine)

  useEffect(() => {
    const onOnline = () => setOnline(true)
    const onOffline = () => setOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  if (online) return null

  return (
    <div className="flex items-center justify-center gap-2 bg-negative/10 border-b border-negative/20 px-3 py-1.5 text-[11px] text-negative shrink-0">
      <span className="inline-block h-2 w-2 rounded-full bg-negative animate-pulse" />
      <span>网络断开 — 数据可能已过时</span>
    </div>
  )
}
