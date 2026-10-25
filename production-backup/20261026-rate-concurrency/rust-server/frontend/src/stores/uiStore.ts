import { create } from 'zustand'

interface UiState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void

  mobileNavOpen: boolean
  setMobileNavOpen: (open: boolean) => void

  wsConnected: boolean
  wsReconnectCount: number
  wsLastConnectedAt: number | null
  setWsConnected: (connected: boolean) => void
  incrementWsReconnectCount: () => void
  resetWsReconnectCount: () => void
  setWsLastConnectedAt: (ts: number | null) => void
}

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

  mobileNavOpen: false,
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),

  wsConnected: false,
  wsReconnectCount: 0,
  wsLastConnectedAt: null,
  setWsConnected: (connected) => set({ wsConnected: connected }),
  incrementWsReconnectCount: () => set((s) => ({ wsReconnectCount: s.wsReconnectCount + 1 })),
  resetWsReconnectCount: () => set({ wsReconnectCount: 0 }),
  setWsLastConnectedAt: (ts) => set({ wsLastConnectedAt: ts }),
}))
