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

// V6 契约实例(/api/v6):同域同鉴权,只有前缀不同
const http6 = axios.create({
  baseURL: (import.meta.env.VITE_MIX_API || 'http://localhost:8100/api/v1').replace(/\/api\/v1\/?$/, '/api/v6'),
  timeout: 15000,
})
http6.interceptors.request.use(cfg => {
  const t = localStorage.getItem('mix_token')
  if (t) cfg.headers['X-Op-Token'] = t
  // REV2 §9:移动端受信设备会话——命令闸据此判受信+额度(桌面无此值=隐式受信)
  const dev = localStorage.getItem('mix_device_session')
  if (dev) cfg.headers['X-Device-Session'] = dev
  return cfg
})
http6.interceptors.response.use(r => r.data, e => {
  if (e?.response?.status === 401 && !location.pathname.startsWith('/wall/')) {
    localStorage.removeItem('mix_token')
    window.dispatchEvent(new Event('mix-auth-required'))
  }
  return Promise.reject(e?.response?.data || e)
})

export const mixApi = {
  enums: () => http.get('/meta/enums'),
  riskSummary: () => http.get('/risk/summary'),
  riskOverrideAdd: (body) => http.post('/risk/overrides', body),
  riskVenue: (venue) => http.get(`/risk/venue/${venue}`),
  riskOpportunities: () => http.get('/risk/opportunities'),
  riskPortfolio: () => http.get('/risk/portfolio'),
  riskCashflows: () => http.get('/risk/cashflows'),
  riskSymbolAnalysis: (symbol) => http.get('/risk/symbol-analysis', { params: { symbol } }),
  riskLab: () => http.get('/risk/lab'),
  c3Overview: () => http.get('/c3/overview'),
  c3Brief: (symbol) => http.get('/c3/brief', { params: { symbol } }),
  closePreview: (symbol) => http.get('/close-preview', { params: { symbol } }),
  proposalCreate: (b) => http.post('/proposal/create', b),
  proposals: () => http.get('/proposals'),
  proposalApprove: (id, code, ticket) => http.post(`/proposal/${id}/approve`, ticket ? { reauth_ticket: ticket } : { code }),
  proposalReject: (id) => http.post(`/proposal/${id}/reject`),
  totpStatus: () => http.get('/totp/status'),
  totpProvision: () => http.post('/totp/provision'),
  totpConfirm: (code) => http.post('/totp/confirm', { code }),
  maintStatus: () => http.get('/maintenance/status'),
  maintPreview: () => http.get('/maintenance/preview'),
  maintStart: (b) => http.post('/maintenance/start', b),
  maintAdvance: (id) => http.post(`/maintenance/${id}/advance`),
  maintDrainPlan: (id, b) => http.post(`/maintenance/${id}/drain-plan`, b),
  maintProgress: (id) => http.get(`/maintenance/${id}/progress`),
  maintRecover: (id, code) => http.post(`/maintenance/${id}/recover`, { totp_code: code }),
  aicoinConfigGet: () => http.get('/system/aicoin-config'),
  aicoinConfigSave: (b) => http.post('/system/aicoin-config', b),
  aicoinConfigTest: (b) => http.post('/system/aicoin-config/test', b),
  aicoinKline: (symbol, period, size = 300) => http.get('/aicoin/kline', { params: { symbol, period, size } }),
  aicoinSearch: (q) => http.get('/aicoin/coin-search', { params: { q } }),
  aicoinLabSave: (b) => http.post('/aicoin/labcase', b),
  aicoinLabList: (symbol) => http.get('/aicoin/labcases', { params: symbol ? { symbol } : {} }),
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
    decisionFeed: () => http.get('/monitor/decision-feed'),
  },

  blacklist: () => http.get('/blacklist'),
  quarantine: () => http.get('/quarantine'),
  navBridge: (days=14) => http.get('/ledger/nav-bridge', { params: { days } }),
  ledgerEntries: (p={}) => http.get('/ledger/entries', { params: p }),
  reconBreaks: () => http.get('/ledger/recon-breaks'),
  navCurrent: () => http.get('/system/nav/current'),
  clientsList: () => http.get('/system/clients'),
  clientGrant: (id, b) => http.post(`/system/clients/${id}/access-grant`, b),
  crCreate: (b) => http.post('/system/capital-requests', b),
  crDryRun: (id) => http.post(`/system/capital-requests/${id}/dry-run`),
  crPost: (id, b) => http.post(`/system/capital-requests/${id}/post`, b),
  crList: (clientId = 0) => http.get('/system/capital-requests', { params: clientId ? { client_id: clientId } : {} }),
  shareEventReverse: (eid, b) => http.post(`/system/share-events/${eid}/reverse`, b),
  shareLedger: () => http.get('/system/share/accounts'),
  userTokenStatus: (uid) => http.get(`/operators/users/${uid}/token`),
  userTokenIssue: (uid, days) => http.post(`/operators/users/${uid}/token`, { days }),
  userTokenRevoke: (uid) => http.delete(`/operators/users/${uid}/token`),
  healthV2: () => http.get('/system/health-v2'),
  accountsCustody: () => http.get('/accounts/custody'),
  auditFacts: (kind, symbol='', days=30) => http.get('/audit/facts', { params: { kind, symbol, days } }),
  rulesDryRun: (b) => http.post('/rules/dry-run', b),
  regInstruments: (venue) => http.get('/registry/instruments', { params: { venue } }),
  regRoutes: () => http.get('/registry/routes'),
  regAssetNetwork: () => http.get('/registry/asset-network'),
  quarantineAdd: (b) => http.post('/risk/overrides', b),
  blacklistAdd: (symbol, reason) => http.post('/blacklist', { symbol, reason }),
  blacklistRemove: (symbol) => http.post('/blacklist/remove', { symbol }),
  coinAction: (symbol, action) => http.post(`/coins/${symbol}/actions`, { action }),
  coinMenu: (symbol, body) => http.post(`/coins/${symbol}/menu`, body),
  repayPanel: (symbol) => http.get(`/coins/${symbol}/repay-panel`),
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
  notifyAiGet: () => http.get('/notify/ai'),
  notifyAiSave: (b) => http.put('/notify/ai', b),
  notifyAiTest: (b) => http.post('/notify/ai/test', b || {}),
  llmHistory: () => http.get('/system/llm/history'),
  // 150s > 后端最坏路径(两站×55s+开销)——前端超时必须罩住后端降级链,否则答案生成完前端已放弃
  aiChat: (body) => http.post('/ai/chat', body, { timeout: 150000 }),
  aiModels: () => http.get('/ai/models'),
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
  // edge-tts 真人声(blob;失败时前端回落浏览器 speechSynthesis)
  ttsBlob: (text, persona, opts = {}) =>
    http.get('/notify/tts', { params: { text, persona, ...opts }, responseType: 'blob', timeout: 30000 }),
  ttsPregen: () => http.post('/notify/tts/pregen', null, { timeout: 180000 }),
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
    llmRelayRole: (id, role = 'primary') => http.post(`/system/llm/relays/${id}/set-role`, { role }),
    llmRelayToggle: (id, enabled) => http.post(`/system/llm/relays/${id}/toggle`, { enabled }),
    llmRelayModels: (id) => http.post(`/system/llm/relays/${id}/refresh-models`),
    llmProbeModels: (b) => http.post('/system/llm/probe-models', b),
    llmRelayTest: (id, model) => http.post(`/system/llm/relays/${id}/test-model`, { model }, { timeout: 35000 }),
    llmAgentsGet: () => http.get('/system/llm/agents'),
    llmAgentsPut: (b) => http.put('/system/llm/agents', b),
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
  siteConfig: () => http.get('/site/config'),
  siteBlockPut: (key, b) => http.put(`/site/blocks/${key}`, b),
  registryPut: (b) => http.put('/accounts/registry', b),
  accountMasters: (venue = '') => http.get('/accounts/masters', { params: venue ? { venue } : {} }),
  setAccountMaster: (ak, master_key) => http.put(`/accounts/${encodeURIComponent(ak)}/master`, { master_key }),
  setAccountMode: (ak, account_mode) => http.put(`/accounts/${encodeURIComponent(ak)}/mode`, { account_mode }),
  eligibility: () => http.get('/risk/eligibility'),
  eligibilityPut: (b) => http.put('/risk/eligibility', b),
  accountsBatch: (b) => http.put('/accounts/batch', b),
  coins: () => http.get('/coins'),
  alerts: (strategy = '') => http.get('/alerts', { params: strategy ? { strategy } : {} }),
  reportPnl: (range = '30d') => http.get('/report/pnl', { params: { range } }),
  attribution: () => http.get('/report/attribution'),
  // ── V6 契约(/api/v6):统一快照/工作项/typed命令/写入租约/旧C3.S对比/LAB ──
  // V6.2 PATCH-01:canonical 搜索 / 研判上下文 / 研判案件 / C2.P 人工计划(挂 /api/v6,不开第三前缀)
  instrumentsSearch: (q) => http6.get('/instruments/search', { params: { q } }),
  researchContext: (symbol, product = 'C2.P') => http6.get('/research/context', { params: { symbol, product } }),
  researchCases: (symbol = '') => http6.get('/research/cases', { params: symbol ? { symbol } : {} }),
  researchCaseCreate: (b) => http6.post('/research/cases', b),
  researchCaseComplete: (id, b = {}) => http6.post(`/research/cases/${id}/complete`, b),
  planCreate: (b) => http6.post('/work-items/create-manual-plan', b),
  planPreview: (p) => http6.get('/work-items/plan-preview', { params: p }),
  uxPageview: (page) => http6.post('/ux/pageview', { page }).catch(() => {}),
  uxPageviews: () => http6.get('/ux/pageviews'),
  // REV2 §9 受信设备(M5):桌面注册/列表/撤销/额度
  v6Bootstrap: (surface = 'desktop') => http6.get('/operator/bootstrap', { params: { surface } }),
  devRegister: (b) => http6.post('/operator/devices/register', b),
  devList: () => http6.get('/operator/devices'),
  devRevoke: (sid) => http6.post(`/operator/devices/${encodeURIComponent(sid)}/revoke`),
  devLimits: (sid, b) => http6.post(`/operator/devices/${encodeURIComponent(sid)}/limits`, b),
  v6Snapshot: () => http6.get('/operator/control/snapshot'),
  v6WorkItems: (p = {}) => http6.get('/operator/workitems', { params: p }),
  v6Command: (b) => http6.post('/operator/commands', b),
  v6CommandLog: () => http6.get('/operator/commands/log'),
  v6LeaseList: () => http6.get('/operator/lease'),
  v6LeaseAcquire: (b) => http6.post('/operator/lease/acquire', b),
  v6LeaseRelease: (b) => http6.post('/operator/lease/release', b),
  v6LegacyCompare: () => http6.get('/operator/legacy/compare'),
  v6LegacyRuns: () => http6.get('/operator/legacy/runs'),
  v6LabHealth: () => http6.get('/lab/health'),
  v6LabProjects: () => http6.get('/lab/projects'),
  v6LabLifecycle: (pid) => http6.get(`/lab/projects/${pid}/lifecycle`),
  v6LabRuns: (project = '') => http6.get('/lab/runs', { params: project ? { project } : {} }),
  v6LabEvidence: (p = {}) => http6.get('/lab/evidence', { params: p }),
  v6LabVerdicts: () => http6.get('/lab/verdicts'),
  v6LabOutbox: () => http6.get('/lab/outbox'),
  v6LabSignals: (p = {}) => http6.get('/lab/signals', { params: p }),
  v6LabCommand: (b) => http6.post('/lab/commands', b),
  v6Training: () => http6.get('/training/courses'),
  v6TrainingStart: (c) => http6.post(`/training/${c}/start`),
  v6TrainingAct: (c, action) => http6.post(`/training/${c}/action`, { action }),
  v6Dictionary: () => http6.get('/meta/dictionary'),
  v6Capabilities: () => http6.get('/meta/capabilities'),
  v6CapabilityPut: (pc, b) => http6.put(`/meta/capabilities/${pc}`, b),
  webauthnRegOptions: () => http.post('/webauthn/register/options'),
  webauthnRegVerify: (b) => http.post('/webauthn/register/verify', b),
  webauthnAuthOptions: () => http.post('/webauthn/auth/options'),
  webauthnAuthVerify: (b) => http.post('/webauthn/auth/verify', b),
  webauthnCreds: () => http.get('/webauthn/credentials'),
}
