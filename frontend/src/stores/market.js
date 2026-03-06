import { defineStore } from 'pinia'
import { ref } from 'vue'

const WS_URL = (import.meta.env.VITE_WS_URL || 'ws://13.115.21.77:8000') + '/ws'

export const useMarketStore = defineStore('market', () => {
  const marketData = ref(null)
  const connected = ref(false)
  const lastMessage = ref(null)

  let ws = null
  let reconnectTimer = null
  let token = null

  function getToken() {
    return localStorage.getItem('token') || ''
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return

    token = getToken()
    const url = token ? `${WS_URL}?token=${token}` : WS_URL

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        // Store last message for components to watch
        lastMessage.value = msg

        if (msg.type === 'market_data' && msg.data) {
          const d = msg.data
          // Normalise field names from SpreadData model
          marketData.value = {
            binance_bid: d.binance_quote?.bid_price ?? d.binance_bid ?? 0,
            binance_ask: d.binance_quote?.ask_price ?? d.binance_ask ?? 0,
            binance_mid: d.binance_mid ?? ((d.binance_quote?.bid_price + d.binance_quote?.ask_price) / 2) ?? 0,
            bybit_bid: d.bybit_quote?.bid_price ?? d.bybit_bid ?? 0,
            bybit_ask: d.bybit_quote?.ask_price ?? d.bybit_ask ?? 0,
            bybit_mid: d.bybit_mid ?? ((d.bybit_quote?.bid_price + d.bybit_quote?.ask_price) / 2) ?? 0,
            timestamp: d.timestamp,
          }
        }
        // Handle risk alert messages from backend
        else if (msg.type === 'risk_alert' && msg.data) {
          // Import notification store dynamically to avoid circular dependency
          import('./notification').then(({ useNotificationStore }) => {
            const notificationStore = useNotificationStore()
            // Use handleRiskAlert to properly handle the alert
            notificationStore.handleRiskAlert(msg.data)
          })
        }
      } catch (e) {
        console.error('WS parse error:', e)
      }
    }

    ws.onclose = () => {
      connected.value = false
      ws = null
      // Reconnect after 10 seconds to prevent rate limiting
      reconnectTimer = setTimeout(connect, 10000)
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    connected.value = false
  }

  // Keep fetchMarketData for any legacy callers — returns last known data
  function fetchMarketData() {
    return Promise.resolve(marketData.value)
  }

  return {
    marketData,
    connected,
    lastMessage,
    connect,
    disconnect,
    fetchMarketData,
  }
})
