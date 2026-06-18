import client from './client'

export async function getSpreads(signal?: AbortSignal) {
  const { data } = await client.get('/api/spreads', { signal })
  return data
}

export async function getSpread(symbol: string) {
  const { data } = await client.get(`/api/spreads/${symbol}`)
  return data
}
