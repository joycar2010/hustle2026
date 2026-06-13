import client from './client'

// ─── User Management ───

export interface UserItem {
  id: number
  username: string
  email: string | null
  display_name: string | null
  role: string
  is_active: boolean
  max_sub_accounts: number
  created_at: string
  last_login_at: string | null
  login_ip: string | null
  feishu_open_id: string | null
  feishu_phone: string | null
  feishu_union_id: string | null
}

export async function listUsers() {
  const { data } = await client.get('/api/admin/users')
  return data as UserItem[]
}

export async function createUser(body: {
  username: string; password: string; email?: string; role?: string; max_sub_accounts?: number
  feishu_open_id?: string; feishu_phone?: string; feishu_union_id?: string
}) {
  const { data } = await client.post('/api/admin/users', body)
  return data
}

export async function updateUser(id: number, body: Partial<{
  email: string; display_name: string; role: string; is_active: boolean; max_sub_accounts: number
  feishu_open_id: string; feishu_phone: string; feishu_union_id: string
}>) {
  const { data } = await client.put(`/api/admin/users/${id}`, body)
  return data
}

export async function deleteUser(id: number) {
  const { data } = await client.delete(`/api/admin/users/${id}`)
  return data
}

export async function resetPassword(id: number, newPassword: string) {
  const { data } = await client.post(`/api/admin/users/${id}/reset-password`, { new_password: newPassword })
  return data
}

// ─── Master Account ───

export interface MasterAccountItem {
  id: number
  user_id: number
  account_name: string | null
  api_key_masked: string
  is_verified: boolean
  created_at: string | null
}

export async function getMasterAccount(userId: number) {
  const { data } = await client.get(`/api/admin/users/${userId}/master-account`)
  return data as MasterAccountItem | null
}

export async function createMasterAccount(userId: number, body: { account_name?: string; api_key: string; api_secret: string }) {
  const { data } = await client.post(`/api/admin/users/${userId}/master-account`, body)
  return data
}

export async function updateMasterAccount(userId: number, body: { account_name?: string; api_key?: string; api_secret?: string }) {
  const { data } = await client.put(`/api/admin/users/${userId}/master-account`, body)
  return data
}

export async function validateMasterAccount(userId: number) {
  const { data } = await client.post(`/api/admin/users/${userId}/master-account/validate`)
  return data as { is_valid: boolean; is_verified: boolean; error?: string }
}

export async function deleteMasterAccount(userId: number) {
  const { data } = await client.delete(`/api/admin/users/${userId}/master-account`)
  return data
}

// ─── Sub-Account Management ───

export interface SubAccountItem {
  id: number
  note: string
  email: string
  is_enabled: boolean
  api_key_masked: string
  margin_enabled: boolean
  futures_enabled: boolean
  spot_enabled: boolean
  positions_count: number
  last_validated_at: string | null
  proxy: { id: number; name: string; host: string; port: number; status: string; region?: string | null; end_date?: string | null; days_left?: number | null } | null
  created_at: string
}

export async function getUserSubAccounts(userId: number) {
  const { data } = await client.get(`/api/admin/users/${userId}/sub-accounts`)
  return data as SubAccountItem[]
}

export async function createSubAccount(userId: number, body: { note: string; email: string; api_key: string; api_secret: string }) {
  const { data } = await client.post(`/api/admin/users/${userId}/sub-accounts`, body)
  return data
}

export async function updateSubAccount(userId: number, saId: number, body: Record<string, unknown>) {
  const { data } = await client.put(`/api/admin/users/${userId}/sub-accounts/${saId}`, body)
  return data
}

export async function deleteSubAccount(userId: number, saId: number) {
  const { data } = await client.delete(`/api/admin/users/${userId}/sub-accounts/${saId}`)
  return data
}

export interface SyncPermissionsResult {
  synced: number
  failed: number
  results: Array<{
    id: number; note: string; status: 'ok' | 'error'
    spot?: boolean; margin?: boolean; futures?: boolean; error?: string
  }>
}

export async function syncSubAccountPermissions(userId: number) {
  const { data } = await client.post(`/api/admin/users/${userId}/sub-accounts/sync-permissions`)
  return data as SyncPermissionsResult
}

export async function getAdminSubAccountBalance(userId: number, saId: number) {
  const { data } = await client.get(`/api/admin/users/${userId}/sub-accounts/${saId}/balance`)
  return data
}

export async function getAdminMasterPermissions(userId: number) {
  const { data } = await client.get(`/api/admin/users/${userId}/master-account/permissions`)
  return data
}

// ─── Engine Control ───

export interface EngineUserStatus {
  user_id: number
  username: string
  status: string
  worker_count: number
  open_positions: number
  total_pnl: string
  last_trade_at: string | null
}

export async function listEngineUsers() {
  const { data } = await client.get('/api/admin/engine/users')
  return data as EngineUserStatus[]
}

export async function startUserEngine(userId: number) {
  const { data } = await client.post(`/api/admin/engine/users/${userId}/start`)
  return data
}

export async function stopUserEngine(userId: number) {
  const { data } = await client.post(`/api/admin/engine/users/${userId}/stop`)
  return data
}

// ─── Dashboard ───

export interface DashboardOverview {
  users: { total: number; active: number }
  positions: { open: number; total_usdt: string; total_funding: string; total_interest: string }
  today: { closed_count: number; pnl: string }
  engines: { running: number; total: number }
  proxies: { total: number; active: number; error: number }
  cert_warnings: Array<{ id: number; domain: string; expires_at: string; days_left: number }>
  ssl_certs: Array<{ id: number; domain: string; expires_at: string | null; days_left: number | null; status: string }>
  server: {
    python_uptime: string
    memory_mb: number
    cpu_percent: number
    pid: number
    redis: { connected: boolean; version: string; used_memory_human: string; connected_clients: number; keys: number }
  }
  feishu: { connected: boolean; token_expires_at: string | null; error: string | null; count: number; webhooks: number }
  engine_users: EngineUserStatus[]
  aicoin: { status: string; connected: boolean; api_key_set: boolean; error?: string }
  ai_chat: Record<string, {
    enabled: boolean; provider: string | null; model: string | null
    today_messages: number; total_conversations: number
  }>
  rust_engine: { status: string; spread_pairs: number; channel_active: boolean }
  websocket: {
    connections: number
    streamers: Array<{ name: string; status: string; count: number }>
  }
  engine_health: {
    status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY'
    stuck_positions: Array<{
      id: number; symbol: string; sub_account_id: number
      status: string; stuck_minutes: number; user_id: number | null
    }>
    stale_workers: Array<{
      scope: string; user_id: number | null
      last_heartbeat: string; stale_seconds: number
    }>
    api_metrics: Record<string, {
      total_calls: number; total_errors: number; rate_limited: number
      error_rate: number; last_error_msg: string | null
    }>
  }
}

export async function getDashboardOverview() {
  const { data } = await client.get('/api/admin/dashboard/overview')
  return data as DashboardOverview
}

// ─── Audit Logs ───

export interface AuditLogItem {
  id: number
  user: string
  user_id: number | null
  action: string
  resource: string
  details: string | null
  ip_address: string | null
  created_at: string | null
}

export async function listAuditLogs(params: Record<string, string | number | undefined>) {
  const { data } = await client.get('/api/admin/audit-logs', { params })
  return data as { items: AuditLogItem[]; total: number; page: number; size: number }
}

// ─── SSL Certificates ───

export interface SSLCert {
  id: number
  cert_name: string
  domain_name: string
  cert_type: string
  issuer: string | null
  subject: string | null
  issued_at: string | null
  expires_at: string | null
  status: string
  is_deployed: boolean
  auto_renew: boolean
  created_at: string
}

export async function listSSLCerts() {
  const { data } = await client.get('/api/admin/ssl/certificates')
  return data as SSLCert[]
}

export async function uploadSSLCert(body: { cert_name: string; domain_name: string; cert_content: string; key_content: string }) {
  const { data } = await client.post('/api/admin/ssl/certificates', body)
  return data
}

export async function deleteSSLCert(id: number) {
  await client.delete(`/api/admin/ssl/certificates/${id}`)
}

export async function deploySSLCert(id: number) {
  const { data } = await client.post(`/api/admin/ssl/certificates/${id}/deploy`)
  return data
}

export async function scanLetsEncryptCerts() {
  const { data } = await client.post('/api/admin/ssl/certificates/scan-letsencrypt')
  return data as { scanned: number; added: number; domains: string[] }
}

// ─── Proxy Management ───

export interface ProxyItem {
  id: number
  name: string
  host: string
  port: number
  protocol: string
  provider: string
  status: string
  health_score: number
  region: string | null
  created_at: string
}

export async function listProxies() {
  const { data } = await client.get('/api/admin/proxies')
  return data as ProxyItem[]
}

export async function createProxy(body: { name: string; host: string; port: number; username?: string; password?: string; protocol?: string; provider?: string; region?: string }) {
  const { data } = await client.post('/api/admin/proxies', body)
  return data
}

export async function deleteProxy(id: number) {
  await client.delete(`/api/admin/proxies/${id}`)
}

export async function healthCheckProxies() {
  const { data } = await client.post('/api/admin/proxies/health-check')
  return data
}

export interface ProxyBinding {
  id: number
  sub_account_id: number
  proxy_id: number
  platform: string
  is_active: boolean
  account_note: string | null
  proxy_name: string | null
}

export async function listProxyBindings() {
  const { data } = await client.get('/api/admin/proxies/bindings')
  return data as ProxyBinding[]
}

export async function bindProxy(body: { sub_account_id: number; proxy_id: number; platform?: string }) {
  const { data } = await client.post('/api/admin/proxies/bind', body)
  return data
}

export async function unbindProxy(id: number) {
  await client.delete(`/api/admin/proxies/bind/${id}`)
}

// ─── IPIPGO ───

export interface IpipgoOrder {
  id: number
  order_no: string
  product_name: string | null
  ip_address: string | null
  port: number | null
  protocol: string | null
  region: string | null
  start_date: string | null
  end_date: string | null
  status: string
  days_left: number | null
}

export async function getIpipgoOrders() {
  const { data } = await client.get('/api/admin/ipipgo/orders')
  return data as IpipgoOrder[]
}

export async function syncIpipgoOrders() {
  const { data } = await client.post('/api/admin/ipipgo/sync')
  return data
}

// ─── WS Monitor ───

export interface WsStats {
  connections: number
  messages_total: number
  uptime_seconds: number
  streamers: Array<{ name: string; status: string; interval: number; message_count: number }>
}

export async function getWsStats() {
  const { data } = await client.get('/api/admin/ws/stats')
  return data as WsStats
}

// ─── Notification Service ───

export interface FeishuConfigItem {
  id: number
  user_id: number | null
  username: string | null
  webhook_url: string
  secret_key: string
  app_id: string
  app_secret: string
  alert_interval_sec: number
  alert_count: number
  margin_rate_alert: number
  leverage_risk_alert: number
  enable_transfer_fail_alert: boolean
  enable_new_borrow_alert: boolean
  is_global: boolean
}

export interface FeishuStatus {
  connected: boolean
  token_expires_at: string | null
  error: string | null
}

export async function getFeishuConfig() {
  const { data } = await client.get('/api/admin/notifications/feishu-config')
  return data as FeishuConfigItem[]
}

export async function updateFeishuConfig(body: Record<string, unknown>) {
  const { data } = await client.put('/api/admin/notifications/feishu-config', body)
  return data
}

export async function getFeishuStatus() {
  const { data } = await client.get('/api/admin/notifications/feishu-status')
  return data as FeishuStatus
}

export async function testFeishuSend(recipient?: string) {
  const params = recipient ? { recipient } : {}
  const { data } = await client.post('/api/admin/notifications/feishu-test', null, { params })
  return data
}

export async function updateUserFeishuConfig(userId: number, body: Record<string, unknown>) {
  const { data } = await client.put(`/api/admin/notifications/feishu-config/user/${userId}`, body)
  return data
}

export async function deleteUserFeishuConfig(userId: number) {
  const { data } = await client.delete(`/api/admin/notifications/feishu-config/user/${userId}`)
  return data
}

export async function feishuLookupByPhone(phone: string) {
  const { data } = await client.post<{ open_id: string; union_id: string }>('/api/auth/feishu-lookup', { phone })
  return data
}

export interface EmailConfigItem {
  smtp_host: string
  smtp_port: number
  smtp_user: string
  smtp_password: string
  smtp_from: string
  use_ssl: boolean
  is_enabled: boolean
}

export async function getEmailConfig() {
  const { data } = await client.get('/api/admin/notifications/email-config')
  return data as EmailConfigItem
}

export async function updateEmailConfig(body: Record<string, unknown>) {
  const { data } = await client.put('/api/admin/notifications/email-config', body)
  return data
}

export async function testEmailSend() {
  const { data } = await client.post('/api/admin/notifications/email-test')
  return data
}

export interface NotificationTemplate {
  id: number
  template_name: string
  category: string
  title_template: string
  content_template: string
  enable_feishu: boolean
  enable_email: boolean
  enable_marquee: boolean
  priority: number
  cooldown_seconds: number
  marquee_color: string
  marquee_blink: boolean
  sound_key: string
  is_enabled: boolean
}

export async function listNotificationTemplates() {
  const { data } = await client.get('/api/admin/notifications/templates')
  return data as NotificationTemplate[]
}

export interface MarqueeItem {
  id: number
  title: string
  content: string
  created_at: string | null
}

export async function getRecentMarquee(limit = 10) {
  const { data } = await client.get('/api/admin/notifications/recent-marquee', { params: { limit } })
  return (data?.items || []) as MarqueeItem[]
}

export async function updateNotificationTemplate(id: number, body: Partial<NotificationTemplate>) {
  const { data } = await client.put(`/api/admin/notifications/templates/${id}`, body)
  return data
}

export async function createNotificationTemplate(body: Partial<NotificationTemplate>) {
  const { data } = await client.post('/api/admin/notifications/templates', body)
  return data
}

export async function deleteNotificationTemplate(id: number) {
  const { data } = await client.delete(`/api/admin/notifications/templates/${id}`)
  return data
}

export async function testNotificationTemplate(id: number, recipient?: string) {
  const { data } = await client.post<{ template: string; channels: Record<string, string> }>(
    `/api/admin/notifications/templates/${id}/test`,
    null,
    { params: recipient ? { recipient } : {} },
  )
  return data
}

export async function broadcastNotification(body: { title: string; content: string; priority: number; color: string; blink: boolean; sound: string }) {
  const { data } = await client.post('/api/admin/notifications/broadcast', body)
  return data
}

export interface SoundPreset {
  key: string
  label: string
}

export async function listSounds() {
  const { data } = await client.get('/api/admin/notifications/sounds')
  return data as SoundPreset[]
}

export interface NotificationLog {
  id: number
  template_name: string
  channel: string
  recipient: string
  status: string
  content_preview: string
  created_at: string
}

export async function listNotificationLogs(params: Record<string, string | number | undefined>) {
  const { data } = await client.get('/api/admin/notifications/logs', { params })
  return data as { items: NotificationLog[]; total: number; page: number; size: number }
}

// ─── System Management ───

export interface SystemInfo {
  backend_version: string
  python_version: string
  db_version: string
  uptime: string
  git_branch: string
  git_commit: string
}

export async function getSystemInfo() {
  const { data } = await client.get('/api/admin/system/info')
  return data as SystemInfo
}

export async function gitPush(body: { message: string }) {
  const { data } = await client.post('/api/admin/system/git-push', body)
  return data
}

export interface GitCommit {
  hash: string
  short_hash: string
  message: string
  author: string
  date: string
}

export async function getGitHistory() {
  const { data } = await client.get('/api/admin/system/git-history')
  return data as GitCommit[]
}

export async function gitRollback(body: { commit_hash: string }) {
  const { data } = await client.post('/api/admin/system/git-rollback', body)
  return data
}

export async function gitDelete(body: { commit_hash: string }) {
  const { data } = await client.post('/api/admin/system/git-delete', body)
  return data
}

export interface ServiceVersion {
  service: string
  host: string
  version?: string
  git_commit: string
  uptime?: string
  last_deploy?: string
  status: string
}

export async function getServiceVersions() {
  const { data } = await client.get('/api/admin/system/versions')
  return data as { services: ServiceVersion[] }
}

export interface DatabaseStats {
  size: string
  table_count: number
  active_connections: number
}

export async function getDatabaseStats() {
  const { data } = await client.get('/api/admin/system/database/stats')
  return data as DatabaseStats
}

export interface TableInfo {
  name: string
  row_count: number
  size: string
}

export async function getDatabaseTables() {
  const { data } = await client.get('/api/admin/system/database/tables')
  return data as TableInfo[]
}

export async function getTableData(tableName: string) {
  const { data } = await client.get(`/api/admin/system/database/tables/${tableName}/data`)
  return data as { columns: string[]; rows: Record<string, unknown>[] }
}

export async function backupDatabase() {
  const { data } = await client.post('/api/admin/system/database/backup')
  return data
}

export async function cleanupDatabase() {
  const { data } = await client.post('/api/admin/system/database/cleanup')
  return data
}

// ─── AiCoin Config ───

export interface AiCoinConfigData {
  api_key: string
  api_secret: string
}

export async function getAicoinConfig() {
  const { data } = await client.get('/api/admin/system/aicoin-config')
  return data as AiCoinConfigData
}

export async function updateAicoinConfig(body: Partial<AiCoinConfigData>) {
  const { data } = await client.put('/api/admin/system/aicoin-config', body)
  return data
}

export async function testAicoinConfig() {
  const { data } = await client.post('/api/admin/system/aicoin-test')
  return data as { status: string; coin_count: number }
}

// ─── AI Support ───

export interface AiFaqItem {
  id: number
  question: string
  answer: string
  category: string
  sort_order: number
  is_active: boolean
  created_at: string
}

export async function listAiFaq() {
  const { data } = await client.get('/api/admin/ai/faq')
  return data as AiFaqItem[]
}

export async function createAiFaq(body: { question: string; answer: string; category: string; sort_order?: number }) {
  const { data } = await client.post('/api/admin/ai/faq', body)
  return data
}

export async function updateAiFaq(id: number, body: Partial<AiFaqItem>) {
  const { data } = await client.put(`/api/admin/ai/faq/${id}`, body)
  return data
}

export async function deleteAiFaq(id: number) {
  await client.delete(`/api/admin/ai/faq/${id}`)
}

export interface AiConfigItem {
  id: number
  site: string
  provider: string
  api_key: string
  base_url: string
  model_name: string
  temperature: number
  max_tokens: number
  system_prompt: string
  is_enabled: boolean
  rate_limit_per_min: number
}

export async function getAiConfig(site = 'default') {
  const { data } = await client.get('/api/admin/ai/config', { params: { site } })
  return data as AiConfigItem
}

export async function updateAiConfig(body: Partial<AiConfigItem>, site = 'default') {
  const { data } = await client.put('/api/admin/ai/config', body, { params: { site } })
  return data
}

// ─── AI Stats & Conversations ───

export interface AiStatsData {
  total_messages: number
  today_messages: number
  active_users: number
  total_tokens: number
  daily_trend: { date: string; count: number }[]
}

export async function getAiStats(site?: string) {
  const { data } = await client.get('/api/admin/ai/stats', { params: site ? { site } : {} })
  return data as AiStatsData
}

export interface AiConversationItem {
  id: number
  site: string
  user_id: number | null
  session_id: string
  title: string
  message_count: number
  token_used: number
  created_at: string | null
  updated_at: string | null
}

export interface AiConversationPage {
  total: number
  page: number
  page_size: number
  items: AiConversationItem[]
}

export async function listAiConversations(params: { site?: string; page?: number; page_size?: number; search?: string }) {
  const { data } = await client.get('/api/admin/ai/conversations', { params })
  return data as AiConversationPage
}

export interface AiMessageItem {
  id: number
  role: string
  content: string
  token_count: number
  created_at: string | null
}

export async function getConversationMessages(conversationId: number) {
  const { data } = await client.get(`/api/admin/ai/conversations/${conversationId}/messages`)
  return data as AiMessageItem[]
}

export interface HotQuestionItem {
  question: string
  count: number
}

export async function getHotQuestions(site?: string) {
  const { data } = await client.get('/api/admin/ai/hot-questions', { params: site ? { site } : {} })
  return data as HotQuestionItem[]
}

// ─── Admin Global Rules ───

export interface GlobalRulesData {
  id: number
  user_id: number | null
  username?: string
  auto_push_spread: string
  remove_spread: string
  open_spread: string
  close_spread: string
  order_amount: string
  close_funding_ratio: string
  repay_funding_ratio: string
  borrow_delay_sec: number
  confirm_delay_sec: number
  confirm_skip_spread: string
  repay_ban_minutes: number
  interest_filter: string
  max_loss_per_position: string | null
  circuit_breaker_spread_pct: string | null
  circuit_breaker_pause_sec: number
  max_daily_interest_rate: string | null
  repay_spread: string | null
  max_positions: number
  auto_start_on_boot: boolean
  futures_liquidation_threshold: string | null
  updated_at: string | null
}

export async function getSystemRules() {
  const { data } = await client.get('/api/admin/global-rules/')
  return data as GlobalRulesData
}

export async function updateSystemRules(body: Record<string, unknown>) {
  const { data } = await client.put('/api/admin/global-rules/', body)
  return data as GlobalRulesData
}

export async function broadcastRules() {
  const { data } = await client.post('/api/admin/global-rules/broadcast')
  return data
}

export async function listUserRules() {
  const { data } = await client.get('/api/admin/global-rules/users')
  return data as GlobalRulesData[]
}

// ─── Market Monitoring ───

export interface AnnouncementItem {
  id: string
  title: string
  url: string
  release_date: number
  is_delist: boolean
}

export async function getAnnouncements() {
  const { data } = await client.get('/api/admin/market/announcements')
  return data as AnnouncementItem[]
}

export async function checkDelist() {
  const { data } = await client.post('/api/admin/market/check-delist')
  return data
}

export interface PendingBlacklistItem {
  id: number
  symbol: string
  reason: string
  source: string
  announcement_title: string | null
  announcement_url: string | null
  created_at: string | null
}

export async function listPendingBlacklist() {
  const { data } = await client.get('/api/admin/market/blacklist-pending')
  return data as PendingBlacklistItem[]
}

export async function confirmBlacklist(id: number) {
  const { data } = await client.post(`/api/admin/market/blacklist-confirm/${id}`)
  return data
}

export async function dismissPending(id: number) {
  const { data } = await client.delete(`/api/admin/market/blacklist-pending/${id}`)
  return data
}

// ─── AiCoin Market Data ───

export async function getKlineData(params: { symbol: string; period: string; size?: number }) {
  const { data } = await client.get('/api/admin/market/kline', { params })
  return data as { data: number[][] }
}

export interface CoinSearchItem {
  coinKey: string
  coinName: string
  coinShow: string
  dbKeys: string
  price: string
  degree24H: string
  logo: string
  market: string
}

export async function searchCoin(q: string) {
  const { data } = await client.get('/api/admin/market/coin-search', { params: { q } })
  return data as CoinSearchItem[]
}

export interface RankingItem {
  symbol: string
  coin_key: string
  price: number
  change_24h: number
  change_5min?: number
  change_7d: number
  vol_24h: number
}

export interface HistoryScoreItem {
  symbol: string
  score: number
}

export interface RankingsData {
  gainers: RankingItem[]
  losers: RankingItem[]
  gainers_5min: RankingItem[]
  historical: HistoryScoreItem[]
}

export async function getRankings() {
  const { data } = await client.get('/api/admin/market/rankings')
  return data as RankingsData
}

export async function resetHistoryScores() {
  const { data } = await client.delete('/api/admin/market/rankings/history')
  return data
}

// ─── RBAC Management ───

export interface RoleItem {
  id: number
  role_name: string
  role_code: string
  description: string
  is_active: boolean
  is_system: boolean
  permission_count: number
  created_at: string | null
}

export interface PermissionItem {
  id: number
  permission_name: string
  permission_code: string
  resource_type: string
  resource_path: string
  http_method: string
  description: string
  sort_order: number
  is_active: boolean
}

export async function listRoles() {
  const { data } = await client.get('/api/admin/rbac/roles')
  return data as RoleItem[]
}

export async function createRole(body: { role_name: string; role_code: string; description?: string; is_active?: boolean }) {
  const { data } = await client.post('/api/admin/rbac/roles', body)
  return data
}

export async function updateRole(id: number, body: { role_name?: string; description?: string; is_active?: boolean }) {
  const { data } = await client.put(`/api/admin/rbac/roles/${id}`, body)
  return data
}

export async function deleteRole(id: number) {
  const { data } = await client.delete(`/api/admin/rbac/roles/${id}`)
  return data
}

export async function getRolePermissions(roleId: number) {
  const { data } = await client.get(`/api/admin/rbac/roles/${roleId}/permissions`)
  return data as number[]
}

export async function assignPermission(roleId: number, permissionId: number) {
  const { data } = await client.post(`/api/admin/rbac/roles/${roleId}/permissions`, { permission_id: permissionId })
  return data
}

export async function revokePermission(roleId: number, permissionId: number) {
  const { data } = await client.delete(`/api/admin/rbac/roles/${roleId}/permissions/${permissionId}`)
  return data
}

export async function listPermissions() {
  const { data } = await client.get('/api/admin/rbac/permissions')
  return data as PermissionItem[]
}

export async function getUserRoles(userId: number) {
  const { data } = await client.get(`/api/admin/rbac/users/${userId}/roles`)
  return data as number[]
}

export async function assignUserRole(userId: number, roleId: number) {
  const { data } = await client.post(`/api/admin/rbac/users/${userId}/roles`, { role_id: roleId })
  return data
}

export async function revokeUserRole(userId: number, roleId: number) {
  const { data } = await client.delete(`/api/admin/rbac/users/${userId}/roles/${roleId}`)
  return data
}

export async function seedRbac() {
  const { data } = await client.post('/api/admin/rbac/seed')
  return data
}
