import axios from 'axios'
import router from '@/router'

// Same-origin by default: nginx routes /api/* to Go (8080) / Python (8000).
// An explicit VITE_API_BASE_URL override still works for local dev.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  timeout: 120000, // 120 seconds for slow backend startup
})

// Request interceptor — attach Bearer token from localStorage.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ── 401 handling ────────────────────────────────────────────────────────────
// Distinguish "token globally invalid" from "single endpoint sporadic 401".
// Strategy: track distinct request paths returning 401 within a short window.
// If >=2 different paths 401 inside the window, the token itself is bad and
// we force logout. A single endpoint flapping does NOT kick the user out.
//
// Core auth endpoints (/users/me, /auth/*) bypass the heuristic and always
// trigger immediate logout — they're the canonical "is my session valid"
// probes and a 401 there is unambiguous.

const AUTH_ENDPOINTS = ['/api/v1/users/me', '/api/v1/auth/']
const UNAUTH_WINDOW_MS = 15000   // 15s rolling window
const UNAUTH_MIN_PATHS = 2        // >=2 distinct paths = real session failure

const recentUnauthPaths = new Map()   // path -> timestamp

function pathOf(url) {
  if (!url) return ''
  const noQuery = url.split('?')[0]
  return noQuery.replace(/^https?:\/\/[^/]+/, '')
}

function recordUnauth(path) {
  const now = Date.now()
  recentUnauthPaths.set(path, now)
  for (const [p, ts] of recentUnauthPaths) {
    if (now - ts > UNAUTH_WINDOW_MS) recentUnauthPaths.delete(p)
  }
  return recentUnauthPaths.size
}

function performLogout(reason) {
  if (window.location.pathname === '/login') return
  console.warn(`[api] forced logout: ${reason}`)
  localStorage.removeItem('token')
  recentUnauthPaths.clear()
  import('@/stores/auth').then(({ useAuthStore }) => {
    const authStore = useAuthStore()
    authStore.logout()
    router.push('/login')
  })
}

api.interceptors.response.use(
  (response) => {
    const renewed = response.headers['x-new-token']
    if (renewed) {
      localStorage.setItem('token', renewed)
    }
    return response
  },
  (error) => {
    if (error.response?.status !== 401) return Promise.reject(error)

    const path = pathOf(error.config?.url || '')

    if (AUTH_ENDPOINTS.some(e => path.includes(e))) {
      performLogout(`auth endpoint 401: ${path}`)
      return Promise.reject(error)
    }

    const distinctCount = recordUnauth(path)
    if (distinctCount >= UNAUTH_MIN_PATHS) {
      performLogout(`${distinctCount} distinct 401s in ${UNAUTH_WINDOW_MS}ms`)
    }
    return Promise.reject(error)
  }
)

export default api
