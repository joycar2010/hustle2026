import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { useToastStore } from '@/components/ui/toast'

// 自定义 axios 配置项参与类型检查:
//   __silent  — 不弹错误 toast
//   __noRetry — 跳过自动重试。git 推送等长任务/非幂等操作必须禁用:客户端超时后重发会在
//               服务器并发再起 git → 抢 .git/index.lock 撞锁(本次"老是提交失败"的放大器之一)。
declare module 'axios' {
  export interface AxiosRequestConfig<D = any> {
    __silent?: boolean
    __noRetry?: boolean
  }
}

const RETRY_MAX = 3
const RETRY_BASE_DELAY = 1000
const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504])

interface RetryConfig extends InternalAxiosRequestConfig {
  __retryCount?: number
  __silent?: boolean
  __noRetry?: boolean
}

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_jwt_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined
    if (!config) return Promise.reject(error)

    const status = error.response?.status
    const isRetryable = !status || RETRYABLE_STATUSES.has(status)
    const retryCount = config.__retryCount || 0

    if (isRetryable && !config.__noRetry && retryCount < RETRY_MAX) {
      config.__retryCount = retryCount + 1
      const delay = RETRY_BASE_DELAY * Math.pow(2, retryCount)
      await new Promise((r) => setTimeout(r, delay))
      return client(config)
    }

    if (status === 401) {
      localStorage.removeItem('admin_jwt_token')
      if (!window.location.pathname.endsWith('/login')) {
        window.location.href = '/admin/login'
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
