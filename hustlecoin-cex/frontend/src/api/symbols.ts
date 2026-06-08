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

export async function getRiskySymbols(): Promise<string[]> {
  const { data } = await client.get('/api/symbols/risky')
  return data
}

export async function toggleSymbolRisk(symbol: string, isRisky: boolean) {
  const { data } = await client.patch(`/api/symbols/${symbol}/risk`, { is_risky: isRisky })
  return data
}
