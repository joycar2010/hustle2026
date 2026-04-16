import axios from 'axios'
import router from '@/router/index.js'

// 使用相对路径（空 baseURL），让请求走 www.hustle2026.xyz/api/...
// nginx 已配置将 /api/ 代理到后端，无跨域问题
const api = axios.create({ baseURL: '', timeout: 60000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('www_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

const AUTH_ENDPOINTS = ['/api/v1/users/me', '/api/v1/auth/']

api.interceptors.response.use(
  res => res,
  error => {
    const url = error.config?.url || ''
    const isAuthEndpoint = AUTH_ENDPOINTS.some(e => url.includes(e))
    if (error.response?.status === 401 && isAuthEndpoint && window.location.pathname !== '/login') {
      localStorage.removeItem('www_token')
      import('@/stores/auth.js').then(({ useAuthStore }) => { useAuthStore().logout(); router.push('/login') })
    }
    return Promise.reject(error)
  }
)

export default api
