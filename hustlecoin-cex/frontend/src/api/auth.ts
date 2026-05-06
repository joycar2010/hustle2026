import client from './client'

export async function login(username: string, password: string) {
  const { data } = await client.post<{ access_token: string }>('/api/auth/login', {
    username,
    password,
  })
  return data
}

export async function initAdmin(username: string, password: string) {
  const { data } = await client.post('/api/auth/init', { username, password })
  return data
}

export interface UserProfile {
  id: number
  username: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  max_sub_accounts: number
  last_login_at: string | null
  feishu_open_id: string
  feishu_phone: string
  feishu_union_id: string
}

export async function getProfile() {
  const { data } = await client.get<UserProfile>('/api/auth/me')
  return data
}

export async function updateProfile(payload: Partial<UserProfile & { password: string }>) {
  const { data } = await client.put('/api/auth/profile', payload)
  return data
}

export async function feishuLookup(phone: string) {
  const { data } = await client.post<{ open_id: string; union_id: string }>('/api/auth/feishu-lookup', { phone })
  return data
}
