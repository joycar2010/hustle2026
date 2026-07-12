// HustleCoin Mix API 客户端 —— 联调基线走 mock（VITE_MIX_API），联调后只换 baseURL
// 契约见 hustlecoin-mix-ui/contracts/openapi.yaml；口径参数(view/sort/dir)必填，缺参后端 400
import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_MIX_API || 'http://localhost:8100/api/v1',
  timeout: 12000,
})
// 访问令牌：operator 令牌或只读令牌（后端查 dcm operators 表 sha256 / MIX_READONLY_TOKEN）
http.interceptors.request.use(cfg => {
  const t = localStorage.getItem('mix_token')
  if (t) cfg.headers['X-Op-Token'] = t
  return cfg
})
// 401 → 通知登录门重新弹出（不再 window.prompt,避免与门重复）
http.interceptors.response.use(r => r.data, e => {
  if (e?.response?.status === 401 && !location.pathname.startsWith('/wall/')) {
    localStorage.removeItem('mix_token')
    window.dispatchEvent(new Event('mix-auth-required'))
  }
  return Promise.reject(e?.response?.data || e)
})

export const mixApi = {
  enums: () => http.get('/meta/enums'),
  whoami: () => http.get('/auth/whoami'),
  whoamiWith: (t) => http.get('/auth/whoami', { headers: { 'X-Op-Token': t } }),
  login: (username, password) => http.post('/auth/login', { username, password }),

  positions: ({ view = 'flat', sort = 'opened_at', dir = 'asc', strategy = '' } = {}) =>
    http.get('/positions', { params: { view, sort, dir, ...(strategy ? { strategy } : {}) } }),
  positionAction: (id, action, accountId, idempotencyKey) =>
    http.post(`/positions/${id}/actions`, { action, accountId, idempotencyKey }),

  strategies: () => http.get('/strategies'),
  strategy: (code) => http.get(`/strategies/${code}`),
  strategyToggle: (code) => http.post(`/strategies/${code}/toggle`),

  rules: (scope) => http.get('/rules', { params: { scope } }),
  rulesSave: (scopeKey, body) => http.put(`/rules/${encodeURIComponent(scopeKey)}`, body),

  accounts: () => http.get('/accounts'),
  accountCreate: (body) => http.post('/accounts', body),
  accountAction: (id, action) => http.post(`/accounts/${id}/actions`, { action }),

  kmsWallets: () => http.get('/kms/wallets'),
  kmsTransfer: (body) => http.post('/kms/transfers', body),
  kmsApprove: (id) => http.post(`/kms/transfers/${id}/approve`),

  monitor: {
    heartbeats: () => http.get('/monitor/heartbeats'),
    freshness: () => http.get('/monitor/freshness'),
    watermarks: () => http.get('/monitor/balance-watermarks'),
    spreads: () => http.get('/monitor/spreads'),
    borrowables: () => http.get('/monitor/borrowables'),
    overview: () => http.get('/monitor/overview'),
    events: () => http.get('/monitor/events'),
  },

  blacklist: () => http.get('/blacklist'),
  coins: () => http.get('/coins'),
  alerts: (strategy = '') => http.get('/alerts', { params: strategy ? { strategy } : {} }),
  reportPnl: (range = '30d') => http.get('/report/pnl', { params: { range } }),
  attribution: () => http.get('/report/attribution'),
}
