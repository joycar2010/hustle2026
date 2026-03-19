import { defineStore } from 'pinia'
import { ref } from 'vue'

const WS_URL = (import.meta.env.VITE_WS_URL || 'ws://13.115.21.77:8000') + '/ws'

export const useMarketStore = defineStore('market', () => {
  const marketData = ref(null)
  const accountBalanceData = ref(null) // 新增：账户余额数据
  const connected = ref(false)
  const lastMessage = ref(null)
  // Real-time position snapshot — updated on every position_snapshot WebSocket message
  const positionSnapshot = ref({
    bybit_long_lots: 0,
    bybit_short_lots: 0,
    binance_long_xau: 0,
    binance_short_xau: 0,
  })

  let ws = null
  let reconnectTimer = null
  let token = null

  function getToken() {
    return localStorage.getItem('token') || ''
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      console.log('[WebSocket] Already connected or connecting, skipping')
      return
    }

    token = getToken()

    // If no token, don't try to connect
    if (!token) {
      console.log('No token available, skipping WebSocket connection')
      return
    }

    const url = `${WS_URL}?token=${token}`
    console.log('[WebSocket] Connecting to:', url)

    ws = new WebSocket(url)

    ws.onopen = () => {
      console.log('[WebSocket] Connected successfully')
      connected.value = true
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      // 连接成功后立即请求持仓快照，避免等待30s定时广播
      ws.send(JSON.stringify({ type: 'request_snapshot' }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        // Debug: log account_balance messages
        if (msg.type === 'account_balance') {
          console.log('[WebSocket] Received account_balance message', new Date().toISOString())
        }

        // Store last message for components to watch
        lastMessage.value = msg

        if (msg.type === 'position_snapshot' && msg.data) {
          // Update positionSnapshot ref directly — StrategyPanel watches this for real-time position display
          positionSnapshot.value = {
            bybit_long_lots: msg.data.bybit_long_lots ?? 0,
            bybit_short_lots: msg.data.bybit_short_lots ?? 0,
            binance_long_xau: msg.data.binance_long_xau ?? 0,
            binance_short_xau: msg.data.binance_short_xau ?? 0,
          }
        } else if (msg.type === 'account_balance' && msg.data) {
          // Also sync positionSnapshot from account_balance if positions are present
          const positions = msg.data.positions || []
          const accounts = msg.data.accounts || []
          if (positions.length > 0) {
            let bybitLong = 0, bybitShort = 0, binanceLong = 0, binanceShort = 0
            positions.forEach(pos => {
              const acc = accounts.find(a => a.account_id === pos.account_id)
              if (!acc) return
              const size = Math.abs(pos.size || 0)
              if (acc.platform_id === 2) {
                if (pos.side === 'Buy') bybitLong += size
                else if (pos.side === 'Sell') bybitShort += size
              } else if (acc.platform_id === 1) {
                if (pos.side === 'Buy') binanceLong += size
                else if (pos.side === 'Sell') binanceShort += size
              }
            })
            positionSnapshot.value = {
              bybit_long_lots: bybitLong,
              bybit_short_lots: bybitShort,
              binance_long_xau: binanceLong,
              binance_short_xau: binanceShort,
            }
          }
        }

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
        // Handle account balance updates
        else if (msg.type === 'account_balance' && msg.data) {
          accountBalanceData.value = msg.data
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

    ws.onclose = (event) => {
      connected.value = false
      ws = null

      // If closed due to authentication failure (code 1008), don't reconnect
      // User needs to login again
      if (event.code === 1008) {
        console.log('WebSocket authentication failed, redirecting to login')
        // Clear token and redirect to login
        localStorage.removeItem('token')
        // Use router to navigate without page reload
        import('@/router').then(({ default: router }) => {
          if (window.location.pathname !== '/login') {
            router.push('/login')
          }
        })
        return
      }

      // For other close reasons, reconnect after 10 seconds
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

  // Request an immediate position snapshot from the backend (bypasses 30s broadcast cycle)
  function requestSnapshot() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'request_snapshot' }))
    }
  }

  return {
    marketData,
    accountBalanceData,
    connected,
    lastMessage,
    positionSnapshot,
    connect,
    disconnect,
    fetchMarketData,
    requestSnapshot,
  }
})
