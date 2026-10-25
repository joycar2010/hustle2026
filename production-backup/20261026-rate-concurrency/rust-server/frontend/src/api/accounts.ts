import client from './client'

export async function getSubAccounts(enabledOnly = false) {
  const { data } = await client.get('/api/sub-accounts/', {
    params: enabledOnly ? { enabled_only: true } : {},
  })
  return data
}

export async function getSubAccount(id: number) {
  const { data } = await client.get(`/api/sub-accounts/${id}`)
  return data
}

export async function createSubAccount(body: Record<string, unknown>) {
  const { data } = await client.post('/api/sub-accounts/', body)
  return data
}

export async function updateSubAccount(id: number, body: Record<string, unknown>) {
  const { data } = await client.put(`/api/sub-accounts/${id}`, body)
  return data
}

export async function deleteSubAccount(id: number, hard = false) {
  const { data } = await client.delete(`/api/sub-accounts/${id}`, {
    params: hard ? { hard: true } : {},
  })
  return data
}

export async function updateSubAccountKeys(id: number, body: Record<string, unknown>, validate = true) {
  const { data } = await client.put(`/api/sub-accounts/${id}/keys`, body, {
    params: { validate },
  })
  return data
}

export async function validateSubAccount(id: number) {
  const { data } = await client.post(`/api/sub-accounts/${id}/validate`)
  return data
}

export async function toggleSubAccount(id: number) {
  const { data } = await client.post(`/api/sub-accounts/${id}/toggle`)
  return data
}

export interface DeactivatePrecheck {
  can_deactivate: boolean
  reason: string
  open_count: number
  borrowed_assets: { asset: string; amount: number }[]
  has_master: boolean
}

export async function deactivatePrecheck(id: number) {
  const { data } = await client.get(`/api/sub-accounts/${id}/deactivate-precheck`)
  return data as DeactivatePrecheck
}

export async function deactivateSubAccount(id: number, body: { mode: 'disable' | 'delete'; transfer_to_master: boolean }) {
  const { data } = await client.post(`/api/sub-accounts/${id}/deactivate`, body)
  return data as { message: string; mode: string; transferred: { asset: string; amount: number; from: string }[] }
}

export async function getMasterAccount() {
  const { data } = await client.get('/api/master-account/')
  return data
}

export async function updateMasterAccount(body: Record<string, unknown>) {
  const { data } = await client.post('/api/master-account/', body)
  return data
}

export async function validateMasterAccount() {
  const { data } = await client.post('/api/master-account/validate')
  return data
}

export async function getIpWhitelist(id: number) {
  const { data } = await client.get(`/api/sub-accounts/${id}/ip-whitelist`)
  return data
}

export async function updateIpWhitelist(id: number, body: { ip_restrict: boolean; ip_list: string[] }) {
  const { data } = await client.put(`/api/sub-accounts/${id}/ip-whitelist`, body)
  return data
}

export async function removeIpFromWhitelist(id: number, ip: string) {
  const { data } = await client.delete(`/api/sub-accounts/${id}/ip-whitelist/${ip}`)
  return data
}

export async function patchSubAccountFundParams(id: number, body: Record<string, unknown>) {
  const { data } = await client.patch(`/api/sub-accounts/${id}/fund-params`, body)
  return data
}

export async function clearSubAccount(id: number, mode: 'disable_only' | 'disable_and_close') {
  const { data } = await client.post(`/api/sub-accounts/${id}/clear`, { mode })
  return data
}

export async function getServerIp(): Promise<{ ip: string }> {
  const { data } = await client.get('/api/sub-accounts/server-ip')
  return data
}

export async function getApiPermissions(id: number) {
  const { data } = await client.get(`/api/sub-accounts/${id}/permissions`)
  return data
}

export async function checkPermissions(body: { api_key: string; api_secret: string }) {
  const { data } = await client.post('/api/sub-accounts/check-permissions', body)
  return data
}

export async function getMasterPermissions() {
  const { data } = await client.get('/api/master-account/permissions')
  return data
}

export async function getMasterBalance() {
  const { data } = await client.get('/api/master-account/balance')
  return data
}
