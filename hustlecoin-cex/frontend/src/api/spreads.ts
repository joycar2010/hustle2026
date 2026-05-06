import client from './client'

export async function getSpreads() {
  const { data } = await client.get('/api/spreads')
  return data
}

export async function getSpread(symbol: string) {
  const { data } = await client.get(`/api/spreads/${symbol}`)
  return data
}
