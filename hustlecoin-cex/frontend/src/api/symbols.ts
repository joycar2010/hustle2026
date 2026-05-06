import client from './client'

export async function getSymbols() {
  const { data } = await client.get('/api/symbols/')
  return data
}

export async function syncSymbols() {
  const { data } = await client.post('/api/symbols/sync')
  return data
}

export async function getSymbolStats() {
  const { data } = await client.get('/api/symbols/stats')
  return data
}
