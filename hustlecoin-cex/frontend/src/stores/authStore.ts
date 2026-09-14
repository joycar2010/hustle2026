import { create } from 'zustand'
import { login as apiLogin } from '@/api/auth'

interface AuthState {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  loadFromStorage: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  username: null,
  isAuthenticated: false,

  login: async (username, password) => {
    const { access_token } = await apiLogin(username, password)
    localStorage.setItem('cex_jwt_token', access_token)
    set({ token: access_token, username, isAuthenticated: true })
  },

  logout: () => {
    localStorage.removeItem('cex_jwt_token')
    set({ token: null, username: null, isAuthenticated: false })
  },

  loadFromStorage: () => {
    const token = localStorage.getItem('cex_jwt_token')
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]))
        const now = Date.now() / 1000
        if (payload.exp && payload.exp > now) {
          set({ token, username: payload.sub || 'admin', isAuthenticated: true })
          return
        }
      } catch {
        // invalid token
      }
      localStorage.removeItem('cex_jwt_token')
    }
    set({ token: null, username: null, isAuthenticated: false })
  },
}))
