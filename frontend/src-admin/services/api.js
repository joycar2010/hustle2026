import axios from 'axios'
import router from '@/router/index.js'

// 使用相对路径（空 baseURL），让请求走 admin.hustle2026.xyz/api/...
// nginx 已配置将 /api/ 代理到后端，无跨域问题
const api = axios.create({ baseURL: '', timeout: 120000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('admin_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Any 401 means token is invalid/expired — clear and redirect to login
api.interceptors.response.use(
  res => res,
  error => {
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      localStorage.removeItem('admin_token')
      localStorage.removeItem('admin_role')
      import('@/stores/auth.js').then(({ useAuthStore }) => {
        useAuthStore().logout()
        router.push('/login')
      })
    }
    return Promise.reject(error)
  }
)

export default api
