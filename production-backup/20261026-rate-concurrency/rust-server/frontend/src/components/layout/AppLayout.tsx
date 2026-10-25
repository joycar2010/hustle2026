import { Outlet } from 'react-router-dom'
import { OwlTopBar } from './OwlTopBar'
import { PageModalHost } from './PageModalHost'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useUiStore } from '@/stores/uiStore'
import { FloatingChatWidget } from '../FloatingChatWidget'

function WsStatusBar() {
  const wsConnected = useUiStore((s) => s.wsConnected)
  const reconnectCount = useUiStore((s) => s.wsReconnectCount)
  const resetWsReconnectCount = useUiStore((s) => s.resetWsReconnectCount)

  if (wsConnected) return null

  // 多次重连仍未连上:仍在自动退避重连(已去掉硬上限,绝不放弃),同时提供手动立即重连
  if (reconnectCount >= 10) {
    return (
      <div className="flex items-center justify-center gap-2 bg-negative/10 border-b border-negative/20 px-3 py-1.5 text-[11px] text-negative shrink-0">
        <span className="inline-block h-2 w-2 rounded-full bg-negative animate-pulse" />
        <span>连接断开 — 持续重连中 ({reconnectCount})</span>
        <button
          onClick={() => {
            resetWsReconnectCount()
            window.dispatchEvent(new Event('ws:manual-reconnect'))
          }}
          className="px-2 py-0.5 bg-primary/20 text-primary rounded text-[10px] hover:bg-primary/30"
        >
          立即重连
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center gap-2 bg-negative/10 border-b border-negative/20 px-3 py-1 text-[11px] text-negative shrink-0">
      <span className="inline-block h-2 w-2 rounded-full bg-negative animate-pulse" />
      <span>连接断开 — 正在重连 ({reconnectCount})</span>
    </div>
  )
}

export function AppLayout() {
  useWebSocket()

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <OwlTopBar />
      <WsStatusBar />
      <main className="flex-1 overflow-auto p-3">
        <Outlet />
      </main>
      <FloatingChatWidget />
      <PageModalHost />
    </div>
  )
}
