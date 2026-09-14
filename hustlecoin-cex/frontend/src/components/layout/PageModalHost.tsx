import { useEffect, useRef, useState, lazy, Suspense } from 'react'
import { usePageModalStore } from '@/stores/pageModalStore'

// 顶部导航单击弹出的页面映射(与 router 同源路由 → 页面组件)。
// 懒加载: 与 router 共享同一份按页面拆分的 chunk(否则静态 import 会把全部页面打回主包,代码分割失效)。
// embedded 模式: 页面隐藏自带标题文字(由模态栏统一展示),保留动作按钮;根容器适配模态高度。
type PageComp = React.ComponentType<{ onClose?: () => void; embedded?: boolean }>
const PAGE: Record<string, React.LazyExoticComponent<PageComp>> = {
  '/rules': lazy(() => import('@/pages/RulesPage').then(m => ({ default: m.RulesPage }))),
  '/history': lazy(() => import('@/pages/HistoryPage').then(m => ({ default: m.HistoryPage }))),
  '/accounts': lazy(() => import('@/pages/AccountsPage').then(m => ({ default: m.AccountsPage }))),
  '/spreads': lazy(() => import('@/pages/SpreadsPage').then(m => ({ default: m.SpreadsPage }))),
  '/blacklist': lazy(() => import('@/pages/BlacklistPage').then(m => ({ default: m.BlacklistPage }))),
  '/coins': lazy(() => import('@/pages/CoinManagementPage').then(m => ({ default: m.CoinManagementPage }))),
  '/settings': lazy(() => import('@/pages/SettingsPage').then(m => ({ default: m.SettingsPage }))),
}

export function PageModalHost() {
  const route = usePageModalStore((s) => s.route)
  const label = usePageModalStore((s) => s.label)
  const close = usePageModalStore((s) => s.close)

  // 拖动: 记录相对默认位置的偏移(px)。每次打开新页面归零。
  const [drag, setDrag] = useState({ x: 0, y: 0 })
  const dragState = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null)

  useEffect(() => { setDrag({ x: 0, y: 0 }) }, [route])

  useEffect(() => {
    if (!route) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [route, close])

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const s = dragState.current
      if (!s) return
      setDrag({ x: s.ox + (e.clientX - s.sx), y: s.oy + (e.clientY - s.sy) })
    }
    const onUp = () => { dragState.current = null; document.body.style.userSelect = '' }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [])

  if (!route) return null
  const Page = PAGE[route]
  if (!Page) return null

  const startDrag = (e: React.MouseEvent) => {
    dragState.current = { sx: e.clientX, sy: e.clientY, ox: drag.x, oy: drag.y }
    document.body.style.userSelect = 'none'
  }

  return (
    <div
      className="fixed inset-0 z-[55] flex items-start justify-center bg-black/30 p-4 pt-14"
      onClick={close}
    >
      <div
        className="flex max-h-[calc(100vh-5rem)] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-border bg-background shadow-2xl"
        style={{ transform: `translate(${drag.x}px, ${drag.y}px)` }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 单一标题栏 — 可拖动(页面自带标题在 embedded 下隐藏,避免重复) */}
        <div
          className="flex shrink-0 cursor-move select-none items-center justify-between border-b border-border bg-[#0d0d14] px-4 py-2"
          onMouseDown={startDrag}
        >
          <span className="text-sm font-semibold">{label}</span>
          <div className="flex items-center gap-3" onMouseDown={(e) => e.stopPropagation()}>
            <button
              onClick={() => { const r = route; close(); window.open(r, '_blank', 'noopener') }}
              title="在新标签页打开"
              className="text-[11px] text-muted-foreground hover:text-foreground"
            >
              ↗ 新标签
            </button>
            <button
              onClick={close}
              title="关闭 (Esc)"
              className="px-1 text-lg leading-none text-muted-foreground hover:text-foreground"
            >
              ✕
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <Suspense fallback={<div className="p-6 text-center text-xs text-muted-foreground">加载中...</div>}>
            <Page onClose={close} embedded />
          </Suspense>
        </div>
      </div>
    </div>
  )
}
