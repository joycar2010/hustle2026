import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

export const useMarketStore = defineStore('market', () => {
  const marketData = ref(null)
  const orderBook = ref({ bids: [], asks: [] })
  const recentTrades = ref([])

  async function fetchMarketData(symbol = 'XAUUSDT') {
    try {
      const response = await api.get(`/api/v1/market/data/${symbol}`)
      marketData.value = response.data
      return response.data
    } catch (error) {
      console.error('Failed to fetch market data:', error)
      return null
    }
  }

  async function fetchOrderBook(symbol = 'XAUUSD') {
    try {
      const response = await api.get(`/api/v1/market/orderbook/${symbol}`)
      orderBook.value = response.data
    } catch (error) {
      console.error('Failed to fetch order book:', error)
    }
  }

  return {
    marketData,
    orderBook,
    recentTrades,
    fetchMarketData,
    fetchOrderBook
  }
})
