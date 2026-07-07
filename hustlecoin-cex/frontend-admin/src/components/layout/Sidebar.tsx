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
  ChevronDown,
} from 'lucide-react'

// 菜单分组(qhadmin 同款结构): 总控置顶无组头,其余组头可点击收缩(localStorage 记忆)
export const navItems = [
  { to: '/admin/dashboard', label: '总控面板', icon: LayoutDashboard, group: '总控' },
  { to: '/admin/users', label: '用户管理', icon: Users, group: '经营' },
  { to: '/admin/funds', label: '资金统计', icon: Wallet, group: '经营' },
  { to: '/admin/history', label: '历史交易', icon: History, group: '经营' },
  { to: '/admin/coins', label: '币种管理', icon: Coins, group: '经营' },
  { to: '/admin/global-rules', label: '通用规则', icon: SlidersHorizontal, group: '策略' },
  { to: '/admin/market-monitor', label: '行情检测', icon: AlertTriangle, group: '策略' },
  { to: '/admin/notifications', label: '通知服务', icon: Bell, group: '运维' },
  { to: '/admin/ai-support', label: 'AI 客服', icon: Bot, group: '运维' },
  { to: '/admin/system', label: '系统管理', icon: Settings, group: '运维' },
]
const GROUP_ORDER = ['总控', '经营', '策略', '运维']

export type NavItem = (typeof navItems)[number]

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

// 有序扁平列表 → qhadmin 式分组(组归属固定,组内顺序跟随拖拽保存的全局顺序)
function groupNav(items: NavItem[]) {
  const byGroup = new Map<string, NavItem[]>()
  for (const it of items) {
    const g = it.group || '其它'
    if (!byGroup.has(g)) byGroup.set(g, [])
    byGroup.get(g)!.push(it)
  }
  return GROUP_ORDER.filter((g) => byGroup.has(g)).map((g) => ({
    name: g,
    standalone: g === '总控',
    items: byGroup.get(g)!,
  }))
}

export function isItemActive(to: string, pathname: string): boolean {
  if (to === '/admin/dashboard') return pathname === to || pathname === '/admin' || pathname === '/admin/'
  return pathname.startsWith(to)
}

export function Sidebar() {
  const navOrder = useUiStore((s) => s.navOrder)
  const setNavOrder = useUiStore((s) => s.setNavOrder)
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const closedGroups = useUiStore((s) => s.closedGroups)
  const toggleGroup = useUiStore((s) => s.toggleGroup)
  const navigate = useNavigate()
  const location = useLocation()
  const [dragTo, setDragTo] = useState<string | null>(null)
  const [overTo, setOverTo] = useState<string | null>(null)
  const items = useMemo(() => orderNav(navOrder), [navOrder])
  const groups = useMemo(() => groupNav(items), [items])

  // 拉取后端保存的顺序(按用户,跨设备/下次登录恢复);失败静默走本地缓存/默认
  useEffect(() => {
    getNavOrder().then((r) => { if (r?.order?.length) setNavOrder(r.order) }).catch(() => {})
  }, [setNavOrder])

  const handleDrop = (toPath: string) => {
    const from = dragTo
    setDragTo(null)
    setOverTo(null)
    if (!from || from === toPath) return
    const cur = items.map((i) => i.to)
    const fi = cur.indexOf(from)
    const ti = cur.indexOf(toPath)
    if (fi < 0 || ti < 0) return
    cur.splice(fi, 1)
    cur.splice(ti, 0, from)
    setNavOrder(cur)                    // 本地即时 + localStorage
    saveNavOrder(cur).catch(() => {})   // 后端按用户持久化
  }

  const renderItem = (item: NavItem) => {
    const active = isItemActive(item.to, location.pathname)
    const isDragging = dragTo === item.to
    const isOver = overTo === item.to && dragTo !== null && dragTo !== item.to
    return (
      <div
        key={item.to}
        draggable={!collapsed}
        onDragStart={() => setDragTo(item.to)}
        onDragOver={(e) => { e.preventDefault(); if (overTo !== item.to) setOverTo(item.to) }}
        onDrop={() => handleDrop(item.to)}
        onDragEnd={() => { setDragTo(null); setOverTo(null) }}
        onClick={() => navigate(item.to)}
        title={collapsed ? item.label : '拖动可调整菜单顺序'}
        className={`group flex cursor-pointer select-none items-center rounded-md text-sm transition-colors ${
          collapsed ? 'justify-center px-0 py-2.5 mx-1.5' : 'gap-2.5 px-3 py-2'
        } ${
          active
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'
        } ${isDragging ? 'opacity-40' : ''} ${isOver ? 'ring-1 ring-primary/50' : ''}`}
      >
        <item.icon className="h-4 w-4 shrink-0" />
        {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
        {!collapsed && (
          <GripVertical className="h-3.5 w-3.5 shrink-0 cursor-grab opacity-0 transition-opacity group-hover:opacity-40" />
        )}
      </div>
    )
  }

  return (
    <aside
      className="flex h-full flex-col border-r bg-card transition-[width] duration-200"
      style={{ width: collapsed ? 64 : 210 }}
    >
      {/* logo 区(qhadmin 56px 固定顶栏) */}
      <div className="flex h-14 shrink-0 items-center justify-center gap-2 border-b px-2">
        <img src="/admin/logo.png" alt="HustleCoin" className="w-8 h-8 object-contain shrink-0" />
        {!collapsed && <span className="text-base font-bold text-primary tracking-wide truncate">HustleCoin</span>}
      </div>

      {/* 菜单区自适应: 项多时内部滚动, logo 固定 */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden p-2">
        {groups.map((grp) =>
          grp.standalone ? (
            grp.items.map(renderItem)
          ) : (
            <div key={grp.name}>
              {!collapsed && (
                <div
                  onClick={() => toggleGroup(grp.name)}
                  className="flex cursor-pointer select-none items-center justify-between px-3 pt-2.5 pb-1 text-[11px] tracking-widest text-muted-foreground/70 hover:text-muted-foreground"
                >
                  <span>{grp.name}</span>
                  <ChevronDown
                    className={`h-3 w-3 transition-transform duration-150 ${closedGroups.includes(grp.name) ? '-rotate-90' : ''}`}
                  />
                </div>
              )}
              {(collapsed || !closedGroups.includes(grp.name)) && grp.items.map(renderItem)}
            </div>
          ),
        )}
      </nav>
    </aside>
  )
}

export function MobileNavDrawer() {
  const open = useUiStore((s) => s.mobileNavOpen)
  const setOpen = useUiStore((s) => s.setMobileNavOpen)
  const navOrder = useUiStore((s) => s.navOrder)
  const closedGroups = useUiStore((s) => s.closedGroups)
  const toggleGroup = useUiStore((s) => s.toggleGroup)
  const username = useAuthStore((s) => s.username)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const location = useLocation()
  const items = useMemo(() => orderNav(navOrder), [navOrder])
  const groups = useMemo(() => groupNav(items), [items])

  if (!open) return null

  const renderLink = (item: NavItem) => {
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
  }

  // qhadmin 同款: 抽屉从左滑入 + 遮罩
  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
      <div className="absolute left-0 top-0 bottom-0 w-[220px] bg-card border-r flex flex-col drawer-in-left shadow-2xl">
        <div className="flex h-14 shrink-0 items-center justify-between border-b px-3">
          <div className="flex items-center gap-2">
            <img src="/admin/logo.png" alt="HustleCoin" className="w-7 h-7 object-contain" />
            <div>
              <p className="text-sm font-bold text-primary leading-tight">HustleCoin</p>
              <p className="text-[10px] text-muted-foreground">{username} ({role})</p>
            </div>
          </div>
          <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-accent">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {groups.map((grp) =>
            grp.standalone ? (
              grp.items.map(renderLink)
            ) : (
              <div key={grp.name}>
                <div
                  onClick={() => toggleGroup(grp.name)}
                  className="flex cursor-pointer select-none items-center justify-between px-3 pt-2.5 pb-1 text-[11px] tracking-widest text-muted-foreground/70"
                >
                  <span>{grp.name}</span>
                  <ChevronDown
                    className={`h-3 w-3 transition-transform duration-150 ${closedGroups.includes(grp.name) ? '-rotate-90' : ''}`}
                  />
                </div>
                {!closedGroups.includes(grp.name) && grp.items.map(renderLink)}
              </div>
            ),
          )}
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
