import axios from 'axios'
import router from '@/router'

// Same-origin by default: nginx routes /api/* to Go (8080) / Python (8000).
// An explicit VITE_API_BASE_URL override still works for local dev.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  timeout: 120000, // 120 seconds for slow backend startup
})

// Request interceptor
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor - only force logout on core auth endpoints to avoid
// data API failures (redis/status, system/status, etc.) kicking users out
const AUTH_ENDPOINTS = ['/api/v1/users/me', '/api/v1/auth/']

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || ''
    const isAuthEndpoint = AUTH_ENDPOINTS.some(e => url.includes(e))
    if (error.response?.status === 401 && isAuthEndpoint && window.location.pathname !== '/login') {
      localStorage.removeItem('token')
      import('@/stores/auth').then(({ useAuthStore }) => {
        const authStore = useAuthStore()
        authStore.logout()
        router.push('/login')
      })
    }
    return Promise.reject(error)
  }
)

export default api
