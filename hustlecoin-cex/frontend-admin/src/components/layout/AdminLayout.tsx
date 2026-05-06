import { Outlet } from 'react-router-dom'
import { Sidebar, MobileNavDrawer } from './Sidebar'
import { FloatingChatWidget } from '../FloatingChatWidget'
import { NetworkStatusBar } from '../NetworkStatusBar'
import { useUiStore } from '@/stores/uiStore'
import { useIsMobile } from '@/hooks/useIsMobile'
import { Menu } from 'lucide-react'

export function AdminLayout() {
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)
  const isMobile = useIsMobile()

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex md:hidden h-12 items-center justify-between border-b bg-card px-3 shrink-0">
          <div className="flex items-center gap-2">
            <img src="/admin/logo.png" alt="HustleCoin" className="w-7 h-7 object-contain" />
            <span className="text-sm font-bold text-primary">HustleCoin</span>
          </div>
          <button
            onClick={() => setMobileNavOpen(true)}
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
          >
            <Menu size={20} />
          </button>
        </header>

        <NetworkStatusBar />

        <main className={isMobile ? 'flex-1 overflow-auto p-3' : 'flex-1 overflow-auto p-6'}>
          <Outlet />
        </main>
      </div>

      <MobileNavDrawer />
      <FloatingChatWidget />
    </div>
  )
}
