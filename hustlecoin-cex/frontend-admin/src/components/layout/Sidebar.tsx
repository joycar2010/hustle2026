import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { useUiStore } from '@/stores/uiStore'
import { getNavOrder, saveNavOrder } from '@/api/admin'
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
  GripVertical,
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

type NavItem = (typeof navItems)[number]

// 按保存的顺序排列;未知/已存在去重,新增菜单项追加末尾(菜单变更不丢项)
function orderNav(order: string[]): NavItem[] {
  if (!order || !order.length) return navItems
  const map = new Map(navItems.map((i) => [i.to, i]))
  const seen = new Set<string>()
  const out: NavItem[] = []
  for (const to of order) {
    const it = map.get(to)
    if (it && !seen.has(to)) { out.push(it); seen.add(to) }
  }
  for (const it of navItems) if (!seen.has(it.to)) out.push(it)
  return out
}

function isItemActive(to: string, pathname: string): boolean {
  if (to === '/admin/dashboard') return pathname === to || pathname === '/admin' || pathname === '/admin/'
  return pathname.startsWith(to)
}

export function Sidebar() {
  const username = useAuthStore((s) => s.username)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const navOrder = useUiStore((s) => s.navOrder)
  const setNavOrder = useUiStore((s) => s.setNavOrder)
  const navigate = useNavigate()
  const location = useLocation()
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [overIdx, setOverIdx] = useState<number | null>(null)
  const items = useMemo(() => orderNav(navOrder), [navOrder])

  // 拉取后端保存的顺序(按用户,跨设备/下次登录恢复);失败静默走本地缓存/默认
  useEffect(() => {
    getNavOrder().then((r) => { if (r?.order?.length) setNavOrder(r.order) }).catch(() => {})
  }, [setNavOrder])

  const handleDrop = (to: number) => {
    const from = dragIdx
    setDragIdx(null)
    setOverIdx(null)
    if (from === null || from === to) return
    const cur = items.map((i) => i.to)
    const [moved] = cur.splice(from, 1)
    cur.splice(to, 0, moved)
    setNavOrder(cur)                    // 本地即时 + localStorage
    saveNavOrder(cur).catch(() => {})   // 后端按用户持久化
  }

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
        {items.map((item, idx) => {
          const active = isItemActive(item.to, location.pathname)
          const isDragging = dragIdx === idx
          const isOver = overIdx === idx && dragIdx !== null && dragIdx !== idx
          return (
            <div
              key={item.to}
              draggable
              onDragStart={() => setDragIdx(idx)}
              onDragOver={(e) => { e.preventDefault(); if (overIdx !== idx) setOverIdx(idx) }}
              onDrop={() => handleDrop(idx)}
              onDragEnd={() => { setDragIdx(null); setOverIdx(null) }}
              onClick={() => navigate(item.to)}
              title="拖动可调整菜单顺序"
              className={`group flex cursor-pointer select-none items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              } ${isDragging ? 'opacity-40' : ''} ${isOver ? 'ring-1 ring-primary/50' : ''}`}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              <span className="flex-1 truncate">{item.label}</span>
              <GripVertical className="h-3.5 w-3.5 shrink-0 cursor-grab opacity-0 transition-opacity group-hover:opacity-40" />
            </div>
          )
        })}
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
  const navOrder = useUiStore((s) => s.navOrder)
  const username = useAuthStore((s) => s.username)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const location = useLocation()
  const items = useMemo(() => orderNav(navOrder), [navOrder])

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
          {items.map((item) => {
            const isActive = isItemActive(item.to, location.pathname)
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
