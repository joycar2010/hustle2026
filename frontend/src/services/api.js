import axios from 'axios'
import router from '@/router'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
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

// Response interceptor
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Only redirect if not already on login page to prevent redirect loop
      if (window.location.pathname !== '/login') {
        // Clear token from localStorage and authStore
        localStorage.removeItem('token')
        // Import authStore dynamically to avoid circular dependency
        import('@/stores/auth').then(({ useAuthStore }) => {
          const authStore = useAuthStore()
          authStore.logout()
          // Use Vue Router to redirect
          router.push('/login')
        })
      }
    }
    return Promise.reject(error)
  }
)

export default api
