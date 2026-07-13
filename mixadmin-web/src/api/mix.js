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
  strategyMode: (code, mode, confirm) => http.post(`/strategies/${code}/mode`, { mode, ...(confirm ? { confirm } : {}) }),

  rules: (scope) => http.get('/rules', { params: { scope } }),
  rulesSave: (scopeKey, body) => http.put(`/rules/${encodeURIComponent(scopeKey)}`, body),
  symbolRule: (symbol, strategy = 'S3') => http.get(`/rules/symbol/${symbol}`, { params: { strategy } }),
  symbolRuleSave: (symbol, body) => http.put(`/rules/symbol/${symbol}`, body),
  symbolRuleMatrix: (symbol) => http.get(`/rules/symbol/${symbol}/matrix`, { timeout: 20000 }),
  symbolRuleMatrixSave: (symbol, body) => http.put(`/rules/symbol/${symbol}/matrix`, body, { timeout: 20000 }),
  fundRulesS3: () => http.get('/rules/fund/s3', { timeout: 20000 }),
  fundRulesS3Save: (body) => http.put('/rules/fund/s3', body, { timeout: 20000 }),

  accounts: () => http.get('/accounts'),
  accountCreate: (body) => http.post('/accounts', body),
  accountAction: (id, action, extra = {}) => http.post(`/accounts/${id}/actions`, { action, ...extra }),

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
    advisorsChat: () => http.get('/monitor/advisors-chat'),
  },

  blacklist: () => http.get('/blacklist'),
  blacklistAdd: (symbol, reason) => http.post('/blacklist', { symbol, reason }),
  blacklistRemove: (symbol) => http.post('/blacklist/remove', { symbol }),
  coinAction: (symbol, action) => http.post(`/coins/${symbol}/actions`, { action }),
  coinMenu: (symbol, body) => http.post(`/coins/${symbol}/menu`, body),
  transferCreateOrder: (account) => http.post(`/monitor/transfer-suggestions/${account}/create-order`),
  notifyGet: () => http.get('/settings/notifications'),
  notifySave: (b) => http.put('/settings/notifications', b),
  notices: () => http.get('/site/notices'),
  noticePut: (b) => http.put('/site/notices', b),
  noticeDel: (id) => http.delete(`/site/notices/${id}`),
  templates: () => http.get('/notify/templates'),
  templatePut: (b) => http.put('/notify/templates', b),
  templateDel: (id) => http.delete(`/notify/templates/${id}`),
  notifyLogs: () => http.get('/notify/logs'),
  notifyBroadcast: (b) => http.post('/notify/broadcast', b),
  channelsGet: () => http.get('/notify/channels'),
  channelsPut: (b) => http.put('/notify/channels', b),
  llmHistory: () => http.get('/system/llm/history'),
  aiChat: (body) => http.post('/ai/chat', body, { timeout: 65000 }),
  datasources: () => http.get('/meta/datasources'),
  feishuGet: () => http.get('/me/feishu'),
  feishuBind: (b) => http.post('/me/feishu', b),
  feishuLookup: (phone) => http.get('/me/feishu/lookup', { params: { phone } }),
  // 通知模块扩展
  maintenanceGet: () => http.get('/system/maintenance'),
  maintenancePut: (b) => http.put('/system/maintenance', b),
  maintenanceAllStop: (b) => http.post('/system/maintenance/all-stop', b),
  personas: () => http.get('/notify/personas'),
  personaPut: (b) => http.put('/notify/personas', b),
  personaDel: (id) => http.delete(`/notify/personas/${id}`),
  // 账户簿 + 凭证托管
  registryTree: () => http.get('/accounts/registry-tree'),
  registryFull: (b) => http.post('/accounts/registry-full', b),
  credPubkey: () => http.get('/credentials/pubkey'),
  creds: () => http.get('/credentials'),
  credPut: (b) => http.put('/credentials', b),
  credProxy: (key, b) => http.put(`/credentials/${key}/proxy`, b),
  credDel: (key) => http.delete(`/credentials/${key}`),
  rulesAudit: (scopeKey) => http.get(`/rules/${encodeURIComponent(scopeKey)}/audit`),
  registryList: () => http.get('/accounts/registry'),
  history: (range = '30d', strategy = '') => http.get('/history', { params: { range, ...(strategy ? { strategy } : {}) } }),
  historyQ: (params) => http.get('/history', { params }),
  system: {
    status: () => http.get('/system/status'),
    backupDb: () => http.post('/system/backup-db'),
    backupSnapshot: () => http.post('/system/backup-snapshot'),
    sslRenew: () => http.post('/system/ssl-renew'),
    llm: () => http.get('/system/llm'),
    llmRelays: () => http.get('/system/llm/relays'),
    llmRelayAdd: (b) => http.post('/system/llm/relays', b),
    llmRelaySave: (id, b) => http.put(`/system/llm/relays/${id}`, b),
    llmRelayDel: (id) => http.delete(`/system/llm/relays/${id}`),
    llmRelayRole: (id) => http.post(`/system/llm/relays/${id}/set-role`, { role: 'primary' }),
    llmRelayToggle: (id, enabled) => http.post(`/system/llm/relays/${id}/toggle`, { enabled }),
    llmRelayModels: (id) => http.post(`/system/llm/relays/${id}/refresh-models`),
    llmCircuitReset: () => http.post('/system/llm/circuit-reset'),
    llmUsageDaily: (days = 14) => http.get('/system/llm/usage-daily', { params: { days } }),
  },
  operatorsAll: () => http.get('/operators/all'),
  userCreate: (b) => http.post('/auth/users', b),
  userUpdate: (id, b) => http.put(`/operators/users/${id}`, b),
  roles: () => http.get('/operators/roles'),
  rolePut: (b) => http.put('/operators/roles', b),
  roleDel: (k) => http.delete(`/operators/roles/${k}`),
  operatorsAudit: () => http.get('/operators/audit'),
  siteBrand: () => http.get('/site/brand'),
  siteBrandPut: (b) => http.put('/site/brand', b),
  registryPut: (b) => http.put('/accounts/registry', b),
  coins: () => http.get('/coins'),
  alerts: (strategy = '') => http.get('/alerts', { params: strategy ? { strategy } : {} }),
  reportPnl: (range = '30d') => http.get('/report/pnl', { params: { range } }),
  attribution: () => http.get('/report/attribution'),
}
