import { NavLink, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useUiStore } from '@/stores/uiStore'
import {
  LayoutDashboard,
  Users,
  LogOut,
  Bell,
  Settings,
  Bot,
  SlidersHorizontal,
  AlertTriangle,
  Coins,
  History,
  Wallet,
  X,
} from 'lucide-react'

const navItems = [
  { to: '/admin/dashboard', label: '总控面板', icon: LayoutDashboard },
  { to: '/admin/users', label: '用户管理', icon: Users },
  { to: '/admin/funds', label: '资金统计', icon: Wallet },
  { to: '/admin/history', label: '历史交易', icon: History },
  { to: '/admin/global-rules', label: '通用规则', icon: SlidersHorizontal },
  { to: '/admin/market-monitor', label: '行情检测', icon: AlertTriangle },
  { to: '/admin/coins', label: '币种管理', icon: Coins },
  { to: '/admin/notifications', label: '通知服务', icon: Bell },
  { to: '/admin/ai-support', label: 'AI 客服', icon: Bot },
  { to: '/admin/system', label: '系统管理', icon: Settings },
]

export function Sidebar() {
  const username = useAuthStore((s) => s.username)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)

  return (
    <aside className="flex h-full w-56 flex-col border-r bg-card">
      <div className="border-b p-4">
        <div className="flex items-center gap-2.5">
          <img src="/admin/logo.png" alt="HustleCoin" className="w-9 h-9 object-contain" />
          <div>
            <h1 className="text-base font-bold text-primary leading-tight">HustleCoin</h1>
            <p className="text-xs text-muted-foreground">{username} ({role})</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              }`
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t p-2">
        <button
          onClick={logout}
          className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          退出登录
        </button>
      </div>
    </aside>
  )
}

export function MobileNavDrawer() {
  const open = useUiStore((s) => s.mobileNavOpen)
  const setOpen = useUiStore((s) => s.setMobileNavOpen)
  const username = useAuthStore((s) => s.username)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const location = useLocation()

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
      <div className="absolute right-0 top-0 bottom-0 w-[280px] bg-card border-l flex flex-col animate-in slide-in-from-right duration-200">
        <div className="flex items-center justify-between border-b p-4">
          <div className="flex items-center gap-2.5">
            <img src="/admin/logo.png" alt="HustleCoin" className="w-8 h-8 object-contain" />
            <div>
              <p className="text-sm font-bold text-primary">HustleCoin</p>
              <p className="text-[10px] text-muted-foreground">{username} ({role})</p>
            </div>
          </div>
          <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-accent">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {navItems.map((item) => {
            const isActive = location.pathname.startsWith(item.to)
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setOpen(false)}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                }`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>

        <div className="border-t p-2">
          <button
            onClick={() => { logout(); setOpen(false) }}
            className="flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </div>
    </div>
  )
}
