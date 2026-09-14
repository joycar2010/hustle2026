import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { Sidebar, MobileNavDrawer, navItems, isItemActive } from './Sidebar'
import { FloatingChatWidget } from '../FloatingChatWidget'
import { NetworkStatusBar } from '../NetworkStatusBar'
import { useUiStore } from '@/stores/uiStore'
import { useAuthStore } from '@/stores/authStore'
import { useIsMobile } from '@/hooks/useIsMobile'
import { Menu, PanelLeftClose, PanelLeftOpen, ChevronDown, LogOut, UserCircle2, X } from 'lucide-react'

interface TabItem { path: string; label: string }

function navMeta(pathname: string) {
  return navItems.find((n) => isItemActive(n.to, pathname))
}

// qhadmin 同款顶栏时钟(1s 走秒)
function Clock() {
  const [now, setNow] = useState(() => new Date().toTimeString().slice(0, 8))
  useEffect(() => {
    const t = setInterval(() => setNow(new Date().toTimeString().slice(0, 8)), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <span className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground font-mono">
      <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
      {now}
    </span>
  )
}

// 顶栏用户下拉(qhadmin: 用户名(角色) + 权限行 + 退出)
function UserDropdown() {
  const username = useAuthStore((s) => s.username)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[13px] font-semibold text-primary hover:opacity-80 transition-opacity"
      >
        <UserCircle2 className="h-4 w-4" />
        <span className="max-w-[120px] truncate">{username || '管理员'}</span>
        <span className="hidden sm:inline text-muted-foreground font-normal">({role || 'admin'})</span>
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-44 rounded-md border bg-card shadow-lg z-50 py-1">
          <div className="px-3 py-1.5 text-xs text-muted-foreground border-b">角色: {role || 'admin'}</div>
          <button
            onClick={() => { setOpen(false); logout() }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" />
            退出登录
          </button>
        </div>
      )}
    </div>
  )
}

// qhadmin 同款多页签栏: 卡片式可关闭 tab,带功能图标,点击切路由;至少保留 1 个
function TabsBar({ tabs, active, onClick, onClose }: {
  tabs: TabItem[]
  active: string
  onClick: (path: string) => void
  onClose: (path: string) => void
}) {
  return (
    <div className="flex items-center gap-1 border-b bg-card px-2 py-1 overflow-x-auto scrollbar-hide shrink-0">
      {tabs.map((tab) => {
        const meta = navItems.find((n) => n.to === tab.path)
        const Icon = meta?.icon
        const isActive = tab.path === active
        return (
          <div
            key={tab.path}
            onClick={() => onClick(tab.path)}
            className={`group flex shrink-0 cursor-pointer select-none items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors ${
              isActive
                ? 'border-primary/40 bg-primary/10 text-primary font-medium'
                : 'border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent'
            }`}
          >
            {Icon && <Icon className="h-3.5 w-3.5" />}
            <span>{tab.label}</span>
            {tabs.length > 1 && (
              <X
                className="h-3 w-3 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
                onClick={(e) => { e.stopPropagation(); onClose(tab.path) }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

export function AdminLayout() {
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggleCollapsed = useUiStore((s) => s.toggleSidebarCollapsed)
  const isMobile = useIsMobile()
  const location = useLocation()
  const navigate = useNavigate()

  // 多页签(qhadmin 同款,会话级): 访问过的页面成 tab,当前路由自动登记
  const [tabs, setTabs] = useState<TabItem[]>([])
  useEffect(() => {
    const meta = navMeta(location.pathname)
    if (!meta) return
    setTabs((cur) => (cur.find((t) => t.path === meta.to) ? cur : [...cur, { path: meta.to, label: meta.label }]))
  }, [location.pathname])

  const activeMeta = navMeta(location.pathname)
  const activeTab = activeMeta?.to || location.pathname

  const closeTab = (path: string) => {
    setTabs((cur) => {
      if (cur.length <= 1) return cur
      const idx = cur.findIndex((t) => t.path === path)
      const next = cur.filter((t) => t.path !== path)
      if (path === activeTab) {
        const fallback = next[Math.max(0, idx - 1)]
        if (fallback) navigate(fallback.path)
      }
      return next
    })
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 桌面侧栏(可收纳 64px) */}
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      <div className="flex flex-1 flex-col overflow-hidden min-w-0">
        {/* 顶栏(qhadmin 50px): 折叠钮/汉堡 + 弹性区 + 用户下拉 + 状态点时钟 */}
        <header className="flex h-[50px] shrink-0 items-center gap-3 border-b bg-card px-3.5">
          <button
            onClick={() => setMobileNavOpen(true)}
            className="md:hidden p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
          >
            <Menu size={20} />
          </button>
          <button
            onClick={toggleCollapsed}
            title={collapsed ? '展开侧栏' : '收起侧栏'}
            className="hidden md:inline-flex p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent"
          >
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </button>
          <div className="md:hidden flex items-center gap-2">
            <img src="/admin/logo.png" alt="HustleCoin" className="w-6 h-6 object-contain" />
            <span className="text-sm font-bold text-primary">HustleCoin</span>
          </div>
          <span className="flex-1" />
          <UserDropdown />
          <Clock />
        </header>

        <NetworkStatusBar />

        {/* 多页签栏 */}
        <TabsBar tabs={tabs} active={activeTab} onClick={(p) => navigate(p)} onClose={closeTab} />

        {/* 面包屑(qhadmin crumb 行) */}
        <div className="shrink-0 px-4 py-1.5 text-xs text-muted-foreground">
          {activeMeta ? `${activeMeta.group} / ${activeMeta.label}` : ''}
        </div>

        <main className={isMobile ? 'flex-1 overflow-auto px-3 pb-3' : 'flex-1 overflow-auto px-4 pb-4'}>
          <Outlet />
        </main>
      </div>

      <MobileNavDrawer />
      <FloatingChatWidget />
    </div>
  )
}
