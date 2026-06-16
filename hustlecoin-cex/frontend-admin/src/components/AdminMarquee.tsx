import { useEffect, useState } from 'react'
import { getRecentMarquee, type MarqueeItem } from '@/api/admin'
import { Megaphone, X } from 'lucide-react'

// coinadmin 后台内置跑马灯:轮询近 24h 的 marquee 广播(API 文档变动 / 抗延迟巡检等),
// 横向滚动展示「首行摘要」,点击打开详情弹窗看全文报告。admin 无 WebSocket,用 30s 轮询。
export function AdminMarquee() {
  const [items, setItems] = useState<MarqueeItem[]>([])
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  const [detailOpen, setDetailOpen] = useState(false)

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

  // 滚动只显每条 content 的首行(摘要);详情在弹窗看全文
  const firstLine = (c: string) => (c || '').split('\n')[0]
  const segments = visible.map((i) => {
    const ts = i.created_at ? new Date(i.created_at).toLocaleString('zh-CN', { hour12: false }) : ''
    return `📢 ${i.title}:${firstLine(i.content)}${ts ? `(${ts})` : ''}`
  })
  const track = segments.join('　　•　　')

  return (
    <>
      <div className="relative flex items-center gap-2 overflow-hidden rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
        <style>{`@keyframes admin-marquee-scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}`}</style>
        <Megaphone className="h-4 w-4 shrink-0 text-amber-500" />
        <button
          type="button"
          onClick={() => setDetailOpen(true)}
          title="点击查看详情"
          className="relative flex-1 overflow-hidden whitespace-nowrap text-left cursor-pointer"
        >
          <div
            className="inline-block whitespace-nowrap text-amber-200 will-change-transform"
            style={{ animation: `admin-marquee-scroll ${Math.max(18, track.length * 0.35)}s linear infinite` }}
          >
            <span className="px-4">{track}</span>
            <span className="px-4">{track}</span>
          </div>
        </button>
        <button
          onClick={() => setDismissed(new Set(visible.map((i) => i.id)))}
          className="shrink-0 rounded p-0.5 text-amber-400/70 transition-colors hover:bg-amber-500/20 hover:text-amber-200"
          title="关闭(刷新后如仍有新告警会再次出现)"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {detailOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setDetailOpen(false)}
        >
          <div
            className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-lg border border-border bg-card p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Megaphone className="h-4 w-4 text-amber-500" /> 跑马灯告警详情
              </h3>
              <button onClick={() => setDetailOpen(false)} className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3">
              {visible.map((i) => (
                <div key={i.id} className="rounded border border-border bg-muted/30 p-3">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-amber-300">{i.title}</span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {i.created_at ? new Date(i.created_at).toLocaleString('zh-CN', { hour12: false }) : ''}
                    </span>
                  </div>
                  <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">{i.content}</pre>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
