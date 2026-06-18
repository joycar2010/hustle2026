import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { useToastStore } from '@/components/ui/toast'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15000,
})

let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

function getTokenExpiry(token: string): number {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return (payload.exp || 0) * 1000
  } catch {
    return 0
  }
}

client.interceptors.request.use(async (config) => {
  const token = localStorage.getItem('cex_jwt_token')
  if (token) {
    const expiry = getTokenExpiry(token)
    const now = Date.now()
    if (expiry > 0 && expiry - now < 30 * 60 * 1000 && expiry > now) {
      if (!isRefreshing) {
        isRefreshing = true
        try {
          const resp = await axios.post('/api/auth/refresh', null, {
            headers: { Authorization: `Bearer ${token}` },
          })
          const newToken = resp.data.access_token
          localStorage.setItem('cex_jwt_token', newToken)
          pendingRequests.forEach((cb) => cb(newToken))
          pendingRequests = []
          config.headers.Authorization = `Bearer ${newToken}`
        } catch {
          config.headers.Authorization = `Bearer ${token}`
        } finally {
          isRefreshing = false
        }
      } else {
        const newToken = await new Promise<string>((resolve) => {
          pendingRequests.push(resolve)
        })
        config.headers.Authorization = `Bearer ${newToken}`
      }
    } else {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

const RETRY_MAX = 3
const RETRY_BASE_DELAY = 1000
const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504])

interface RetryConfig extends InternalAxiosRequestConfig {
  __retryCount?: number
  __silent?: boolean
}

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined
    if (!config) return Promise.reject(error)

    const status = error.response?.status
    const isRetryable = !status || RETRYABLE_STATUSES.has(status)
    const retryCount = config.__retryCount || 0

    if (isRetryable && retryCount < RETRY_MAX) {
      config.__retryCount = retryCount + 1
      const delay = RETRY_BASE_DELAY * Math.pow(2, retryCount)
      await new Promise((r) => setTimeout(r, delay))
      return client(config)
    }

    if (status === 401) {
      localStorage.removeItem('cex_jwt_token')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    if (!config.__silent && status !== 401) {
      useToastStore.getState().addToast(extractError(error), 'error')
    }

    return Promise.reject(error)
  },
)

export function extractError(err: unknown, fallback = '操作失败'): string {
  const resp = (err as { response?: { data?: unknown; status?: number } })?.response
  if (!resp) return fallback
  const data = resp.data as { detail?: unknown }
  if (!data?.detail) return fallback
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) {
    const msgs = data.detail.map((e: { loc?: string[]; msg?: string }) => {
      const field = e.loc?.slice(-1)[0] || ''
      const FIELD_NAMES: Record<string, string> = {
        username: '用户名', password: '密码', email: '邮箱', note: '备注名',
        api_key: 'API Key', api_secret: 'API Secret', host: '主机', port: '端口',
      }
      return `${FIELD_NAMES[field] || field}: ${e.msg || '格式错误'}`
    })
    return msgs.join('; ')
  }
  return fallback
}

export default client
