import axios from 'axios'
// BFF:同源(gateway 托管 SPA+API);X-Op-Token 走 header(qh_admin 令牌头模式)
const TOKKEY = 'dcm_op_token'
export const getTok = () => localStorage.getItem(TOKKEY) || ''
export const setTok = (t) => localStorage.setItem(TOKKEY, t.trim())
export const clearTok = () => localStorage.removeItem(TOKKEY)

const http = axios.create({ baseURL: '/', timeout: 12000 })
http.interceptors.request.use(c => { c.headers['X-Op-Token'] = getTok(); return c })
http.interceptors.response.use(r => r.data, e => {
  if (e.response && e.response.status === 401) { clearTok(); location.reload() }
  return Promise.reject(e.response || e)
})

export const api = {
  overview: () => http.get('/api/overview'),
  shadow: (hours = 24) => http.get('/api/shadow', { params: { hours } }),
  shadowTrend: (hours = 48) => http.get('/api/shadow_trend', { params: { hours } }),
  config: () => http.get('/api/admin/config'),
  setConfig: (engine, key, val, extra = {}) => http.post('/api/admin/engine_config', { engine, key, val, ...extra }),
  kill: () => http.post('/api/admin/kill', {}),
  routeOff: (body) => http.post('/api/admin/route', body),
  alerts: (limit = 120) => http.get('/api/admin/alerts', { params: { limit } }),
  audit: (limit = 120) => http.get('/api/admin/audit', { params: { limit } }),
  coinPositions: () => http.get('/api/coin/positions'),
  coinCommand: (action, params = {}) => http.post('/api/coin/command', { action, params }),
  pnl: (days = 30) => http.get('/api/pnl', { params: { days } }),
}
