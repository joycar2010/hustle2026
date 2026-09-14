import { create } from 'zustand'
import { login as apiLogin, getMe } from '@/api/auth'

interface AuthState {
  token: string | null
  username: string | null
  role: string | null
  userId: number | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  loadFromStorage: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  username: null,
  role: null,
  userId: null,
  isAuthenticated: false,

  login: async (username, password) => {
    const { access_token } = await apiLogin(username, password)
    localStorage.setItem('admin_jwt_token', access_token)
    try {
      const me = await getMe()
      set({ token: access_token, username: me.username, role: me.role, userId: me.user_id, isAuthenticated: true })
    } catch {
      const payload = JSON.parse(atob(access_token.split('.')[1]))
      set({ token: access_token, username: payload.sub, role: payload.role, userId: payload.user_id, isAuthenticated: true })
    }
  },

  logout: () => {
    localStorage.removeItem('admin_jwt_token')
    set({ token: null, username: null, role: null, userId: null, isAuthenticated: false })
  },

  loadFromStorage: () => {
    const token = localStorage.getItem('admin_jwt_token')
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]))
        const now = Date.now() / 1000
        if (payload.exp && payload.exp > now) {
          set({ token, username: payload.sub, role: payload.role, userId: payload.user_id, isAuthenticated: true })
          return
        }
      } catch { /* invalid token */ }
      localStorage.removeItem('admin_jwt_token')
    }
    set({ token: null, username: null, role: null, userId: null, isAuthenticated: false })
  },
}))
