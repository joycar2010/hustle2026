import { create } from 'zustand'

const NAV_ORDER_KEY = 'admin_nav_order'
const SIDEBAR_COLLAPSED_KEY = 'admin_sidebar_collapsed'
const CLOSED_GROUPS_KEY = 'admin_closed_groups'

function loadNavOrder(): string[] {
  try {
    const c = localStorage.getItem(NAV_ORDER_KEY)
    if (c) { const a = JSON.parse(c); if (Array.isArray(a)) return a }
  } catch { /* ignore */ }
  return []
}

function loadClosedGroups(): string[] {
  try {
    const c = localStorage.getItem(CLOSED_GROUPS_KEY)
    if (c) { const a = JSON.parse(c); if (Array.isArray(a)) return a }
  } catch { /* ignore */ }
  return []
}

interface UiState {
  mobileNavOpen: boolean
  setMobileNavOpen: (open: boolean) => void
  navOrder: string[]                          // 左侧菜单自定义顺序(to 路径数组);空=默认顺序
  setNavOrder: (order: string[]) => void
  sidebarCollapsed: boolean                   // 侧栏收纳(展开↔64px 图标态,qhadmin 同款),localStorage 记忆
  toggleSidebarCollapsed: () => void
  closedGroups: string[]                      // 收起的菜单分组名(qhadmin 同款),localStorage 记忆
  toggleGroup: (name: string) => void
}

export const useUiStore = create<UiState>((set, get) => ({
  mobileNavOpen: false,
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
  navOrder: loadNavOrder(),                    // 本地缓存即时恢复(无闪烁),挂载后再用后端覆盖
  setNavOrder: (order) => {
    try { localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order)) } catch { /* ignore */ }
    set({ navOrder: order })
  },
  sidebarCollapsed: localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1',
  toggleSidebarCollapsed: () => {
    const next = !get().sidebarCollapsed
    try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0') } catch { /* ignore */ }
    set({ sidebarCollapsed: next })
  },
  closedGroups: loadClosedGroups(),
  toggleGroup: (name) => {
    const cur = get().closedGroups
    const next = cur.includes(name) ? cur.filter((g) => g !== name) : [...cur, name]
    try { localStorage.setItem(CLOSED_GROUPS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
    set({ closedGroups: next })
  },
}))
