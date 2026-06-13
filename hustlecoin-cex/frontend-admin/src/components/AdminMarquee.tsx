import { useEffect, useState } from 'react'
import { getRecentMarquee, type MarqueeItem } from '@/api/admin'
import { Megaphone, X } from 'lucide-react'

// coinadmin 后台内置跑马灯:轮询近 24h 的 marquee 广播(API 文档变动等告警),
// 横向滚动展示。admin 应用无 WebSocket,故采用轮询(此类告警很罕见,30s 足够)。
export function AdminMarquee() {
  const [items, setItems] = useState<MarqueeItem[]>([])
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await getRecentMarquee(10)
        if (alive) setItems(data)
      } catch {
        /* 静默:看板其他部分照常 */
      }
    }
    load()
    const t = setInterval(load, 30000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const visible = items.filter((i) => !dismissed.has(i.id))
  if (visible.length === 0) return null

  const segments = visible.map((i) => {
    const ts = i.created_at ? new Date(i.created_at).toLocaleString('zh-CN', { hour12: false }) : ''
    return `📢 ${i.title}:${i.content}${ts ? `(${ts})` : ''}`
  })
  // 拼成一条;内容较短时重复一遍保证滚动连续
  const track = segments.join('　　•　　')

  return (
    <div className="relative flex items-center gap-2 overflow-hidden rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
      <style>{`@keyframes admin-marquee-scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}`}</style>
      <Megaphone className="h-4 w-4 shrink-0 text-amber-500" />
      <div className="relative flex-1 overflow-hidden whitespace-nowrap">
        <div
          className="inline-block whitespace-nowrap text-amber-200 will-change-transform"
          style={{ animation: `admin-marquee-scroll ${Math.max(18, track.length * 0.35)}s linear infinite` }}
        >
          <span className="px-4">{track}</span>
          <span className="px-4">{track}</span>
        </div>
      </div>
      <button
        onClick={() => setDismissed(new Set(visible.map((i) => i.id)))}
        className="shrink-0 rounded p-0.5 text-amber-400/70 transition-colors hover:bg-amber-500/20 hover:text-amber-200"
        title="关闭(刷新后如仍有新告警会再次出现)"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
