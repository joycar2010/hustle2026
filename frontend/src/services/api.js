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
        localStorage.removeItem('token')
        // Use Vue Router instead of window.location to avoid full page reload
        router.push('/login')
      }
    }
    return Promise.reject(error)
  }
)

export default api
