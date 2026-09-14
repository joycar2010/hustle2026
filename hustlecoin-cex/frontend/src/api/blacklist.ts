import client from './client'

export async function getBlacklist() {
  const { data } = await client.get('/api/blacklist/')
  return data
}

export async function addToBlacklist(symbol: string, reason?: string) {
  const { data } = await client.post('/api/blacklist/', { symbol, reason: reason || null })
  return data
}

export async function removeFromBlacklist(symbol: string) {
  const { data } = await client.delete(`/api/blacklist/${symbol}`)
  return data
}

export async function batchAddBlacklist(symbols: string[], reason?: string) {
  const { data } = await client.post('/api/blacklist/bulk', { symbols, reason: reason || null })
  return data
}
