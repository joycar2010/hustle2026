import { create } from 'zustand'

const NAV_ORDER_KEY = 'admin_nav_order'

function loadNavOrder(): string[] {
  try {
    const c = localStorage.getItem(NAV_ORDER_KEY)
    if (c) { const a = JSON.parse(c); if (Array.isArray(a)) return a }
  } catch { /* ignore */ }
  return []
}

interface UiState {
  mobileNavOpen: boolean
  setMobileNavOpen: (open: boolean) => void
  navOrder: string[]                          // 左侧菜单自定义顺序(to 路径数组);空=默认顺序
  setNavOrder: (order: string[]) => void
}

export const useUiStore = create<UiState>((set) => ({
  mobileNavOpen: false,
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
  navOrder: loadNavOrder(),                    // 本地缓存即时恢复(无闪烁),挂载后再用后端覆盖
  setNavOrder: (order) => {
    try { localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order)) } catch { /* ignore */ }
    set({ navOrder: order })
  },
}))
