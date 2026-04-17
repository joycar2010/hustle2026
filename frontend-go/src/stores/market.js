import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useTradingPair } from '@/composables/useTradingPair'

// Same-origin WebSocket by default: nginx routes /ws → Go (8080) /api/v1/ws.
// Runtime construction guarantees wss:// on HTTPS pages (avoids mixed-content blocks).
const WS_URL = (
  import.meta.env.VITE_WS_URL
  || `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`
) + '/ws'

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
    // 全产品对持仓: { pair_code: { mt5_long, mt5_short, binance_long, binance_short } }
    pairs: {},
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
      // Subscribe to current trading pair room for per-pair market data
      const { currentPair } = useTradingPair()
      ws.send(JSON.stringify({ type: 'subscribe', pairs: [currentPair.value] }))
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

        // Global risk_alert handler — must run regardless of which page/component is active.
        // Previously only Risk.vue watched for this, so alerts were lost on TradingDashboard etc.
        if (msg.type === 'risk_alert' && msg.data) {
          // Use Promise chain (not await) since ws.onmessage is sync
          import('@/stores/notification').then(({ useNotificationStore }) => {
            useNotificationStore().handleRiskAlert(msg.data)
          }).catch(e => console.error('[WebSocket] risk_alert dispatch failed:', e))
        }

        if (msg.type === 'position_snapshot' && msg.data) {
          // positionSnapshot 只由 position_snapshot 消息驱动，与 account_balance 完全隔离
          // 避免 account_balance 的 60s 缓存数据覆盖实时持仓快照
          // Read from pairs map using current trading pair
          const { currentPair: _cp } = useTradingPair()
          const _pd = (msg.data.pairs ?? {})[_cp.value] || {}
          positionSnapshot.value = {
            bybit_long_lots: _pd.mt5_long ?? msg.data.bybit_long_lots ?? 0,
            bybit_short_lots: _pd.mt5_short ?? msg.data.bybit_short_lots ?? 0,
            binance_long_xau: _pd.binance_long ?? msg.data.binance_long_xau ?? 0,
            binance_short_xau: _pd.binance_short ?? msg.data.binance_short_xau ?? 0,
            pairs: msg.data.pairs ?? {},
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
        // Go native pusher sends type:"spread" with both Binance+Bybit prices every 500ms
        else if (msg.type === 'spread' && msg.data) {
          const d = msg.data
          marketData.value = {
            binance_bid: d.binance_bid ?? 0,
            binance_ask: d.binance_ask ?? 0,
            binance_mid: d.binance_bid != null ? (d.binance_bid + d.binance_ask) / 2 : 0,
            bybit_bid:   d.bybit_bid   ?? 0,
            bybit_ask:   d.bybit_ask   ?? 0,
            bybit_mid:   d.bybit_bid   != null ? (d.bybit_bid + d.bybit_ask) / 2 : 0,
            timestamp:   d.timestamp,
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

  // Re-subscribe to correct pair room when global pair selector changes
  const { currentPair } = useTradingPair()
  watch(currentPair, (newPair, oldPair) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (oldPair) ws.send(JSON.stringify({ type: 'unsubscribe', pairs: [oldPair] }))
      ws.send(JSON.stringify({ type: 'subscribe', pairs: [newPair] }))
    }
  })

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
