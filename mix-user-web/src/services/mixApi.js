// HustleCoin Mix 用户端 API —— 联调基线走 mock（VITE_MIX_API）；
// merged/self 口径必须显式（历史事故：默认 merged 泄漏到交易面板）
import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_MIX_API || 'http://localhost:8100/api/v1',
  timeout: 12000,
})
// 鉴权：优先用户 JWT(www_token, 登录页颁发)；只读令牌(mix_token)兜底
http.interceptors.request.use(cfg => {
  const jwt = localStorage.getItem('www_token')
  const t = localStorage.getItem('mix_token')
  if (jwt) cfg.headers.Authorization = `Bearer ${jwt}`
  else if (t) cfg.headers['X-Op-Token'] = t
  return cfg
})
// 401 → 回登录页（不再 window.prompt）
http.interceptors.response.use(r => r.data, e => {
  if (e?.response?.status === 401 && window.location.pathname !== '/login') {
    localStorage.removeItem('www_token')
    window.location.href = '/login'
  }
  return Promise.reject(e?.response?.data || e)
})

export const mixApi = {
  siteConfig: () => http.get('/site/config'),   // 开放读:登录框/品牌头 CMS 区块(登录前也能拉)
  earningsSummary: (view) => http.get('/me/earnings/summary', { params: { view } }),
  earningsDaily: () => http.get('/me/earnings/daily'),
  earningsSources: () => http.get('/me/earnings/sources'),
  subaccounts: (view) => http.get('/me/subaccounts', { params: { view } }),
  fundFlows: () => http.get('/me/fund-flows'),
  ledger: () => http.get('/me/ledger'),
  ledgerAdd: (body) => http.post('/me/ledger', body),
}
