import client from './client'

export async function getGlobalRules() {
  const { data } = await client.get('/api/global-rules/')
  return data
}

export async function updateGlobalRules(body: Record<string, unknown>) {
  const { data } = await client.put('/api/global-rules/', body)
  return data
}

export async function getFundRules() {
  const { data } = await client.get('/api/fund-rules/')
  return data
}

export async function updateFundRules(body: Record<string, unknown>) {
  const { data } = await client.put('/api/fund-rules/', body)
  return data
}

export async function getSymbolRules(size = 500) {
  const { data } = await client.get('/api/symbol-rules/', { params: { size } })
  return data
}

export async function getSymbolRule(symbol: string) {
  const { data } = await client.get(`/api/symbol-rules/${symbol}`)
  return data
}

export async function updateSymbolRule(symbol: string, body: Record<string, unknown>) {
  const { data } = await client.put(`/api/symbol-rules/${symbol}`, body)
  return data
}

export async function resetSymbolRule(symbol: string) {
  const { data } = await client.post(`/api/symbol-rules/${symbol}/reset`)
  return data
}

export async function deleteSymbolRule(symbol: string) {
  const { data } = await client.delete(`/api/symbol-rules/${symbol}`)
  return data
}

export async function getBlacklist() {
  const { data } = await client.get('/api/blacklist/')
  return data
}

export async function addToBlacklist(symbol: string, reason?: string) {
  const { data } = await client.post('/api/blacklist/', { symbol, reason })
  return data
}

export async function removeFromBlacklist(symbol: string) {
  const { data } = await client.delete(`/api/blacklist/${symbol}`)
  return data
}
