import client from './client'

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

export async function getKlineData(params: { symbol: string; period: string; size?: number }) {
  const { data } = await client.get('/api/market/kline', { params })
  return data as { data: number[][] }
}

export async function searchCoin(q: string) {
  const { data } = await client.get('/api/market/coin-search', { params: { q } })
  return data as CoinSearchItem[]
}

export async function getRankings() {
  const { data } = await client.get('/api/market/rankings')
  return data as RankingsData
}
