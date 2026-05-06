import client from './client'

export async function login(username: string, password: string) {
  const { data } = await client.post('/api/auth/login', { username, password })
  return data as { access_token: string }
}

export async function initAdmin(username: string, password: string) {
  const { data } = await client.post('/api/auth/init', { username, password })
  return data
}

export async function getMe() {
  const { data } = await client.get('/api/auth/me')
  return data as { username: string; user_id: number; role: string }
}
