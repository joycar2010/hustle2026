import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  Wallet,
  History,
  Users,
  Settings as SettingsIcon,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUiStore } from '@/stores/uiStore'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: '总览' },
  { to: '/spreads', icon: TrendingUp, label: '利差监控' },
  { to: '/positions', icon: Wallet, label: '当前持仓' },
  { to: '/history', icon: History, label: '平仓历史' },
  { to: '/accounts', icon: Users, label: '账户管理' },
  { to: '/rules', icon: SlidersHorizontal, label: '规则配置' },
  { to: '/settings', icon: SettingsIcon, label: '系统设置' },
]

export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggle = useUiStore((s) => s.toggleSidebar)

  return (
    <aside
      className={cn(
        'flex flex-col border-r bg-card transition-all duration-200',
        collapsed ? 'w-16' : 'w-56',
      )}
    >
      <div className="flex h-14 items-center justify-between border-b px-3">
        {!collapsed && (
          <span className="text-sm font-bold tracking-wide text-primary">
            HustleCoin
          </span>
        )}
        <button
          onClick={toggle}
          className="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
      <nav className="flex-1 space-y-1 p-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                collapsed && 'justify-center px-0',
              )
            }
          >
            <item.icon size={18} />
            {!collapsed && <span>{item.label}</span>}
          </NavLink>
        ))}
      </nav>
      <div className="border-t p-3 text-center text-xs text-muted-foreground">
        {!collapsed && 'CEX-CEX v0.2'}
      </div>
    </aside>
  )
}
