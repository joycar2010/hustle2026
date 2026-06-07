import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useTradingPair } from '@/composables/useTradingPair'

// Same-origin WebSocket by default: nginx routes /ws → Rust Engine (8090) /api/v1/ws.
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
  const strategyMessage = ref(null)
  const _STRATEGY_MSG_TYPES = new Set([
    'strategy_trigger_progress',
    'strategy_trigger_reset',
    'strategy_position_change',
    'strategy_execution_started',
    'strategy_execution_completed',
    'strategy_execution_error',
    'strategy_order_executed',
    'strategy_orders_filled',
    'strategy_stop_confirmed',
  ])
  // Real-time position snapshot — updated on every position_snapshot WebSocket message
  const marketRates = ref({ funding: null, swap: null })
  const quoteDivergence = ref(null)  // 行情背离软暂停状态
  const positionSnapshot = ref({
    bybit_long_lots: 0,
    bybit_short_lots: 0,
    binance_long_xau: 0,
    binance_short_xau: 0,
    // 全产品对持仓: { pair_code: { mt5_long, mt5_short, binance_long, binance_short } }
    pairs: {},
  })
  let _snapshotDedupBypassUntil = 0

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

        // Route strategy messages to dedicated ref (avoids triggering unrelated watchers)
        if (_STRATEGY_MSG_TYPES.has(msg.type)) {
          strategyMessage.value = msg
        } else {
          lastMessage.value = msg
        }

        // Global risk_alert handler — must run regardless of which page/component is active.
        // Previously only Risk.vue watched for this, so alerts were lost on TradingDashboard etc.
        if (msg.type === 'risk_alert' && msg.data) {
          // Use Promise chain (not await) since ws.onmessage is sync
          import('@/stores/notification').then(({ useNotificationStore }) => {
            useNotificationStore().handleRiskAlert(msg.data)
          }).catch(e => console.error('[WebSocket] risk_alert dispatch failed:', e))
        }

        if (msg.type === 'market_rates' && msg.data) {
          marketRates.value = msg.data
        }

        if (msg.type === 'quote_divergence' && msg.data) {
          quoteDivergence.value = msg.data
        }

        if (msg.type === 'position_snapshot' && msg.data) {
          const prev = positionSnapshot.value
          const incomingPairs = msg.data.pairs
          const hasPairs = incomingPairs && Object.keys(incomingPairs).length > 0
          const next = {
            bybit_long_lots: msg.data.bybit_long_lots ?? 0,
            bybit_short_lots: msg.data.bybit_short_lots ?? 0,
            binance_long_xau: msg.data.binance_long_xau ?? 0,
            binance_short_xau: msg.data.binance_short_xau ?? 0,
            pairs: hasPairs ? incomingPairs : (prev.pairs ?? {}),
          }
          // Dedup: skip update if flat fields unchanged and pairs values identical
          const flatSame = (next.bybit_long_lots === prev.bybit_long_lots &&
                            next.bybit_short_lots === prev.bybit_short_lots &&
                            next.binance_long_xau === prev.binance_long_xau &&
                            next.binance_short_xau === prev.binance_short_xau)
          const pairsSame = flatSame && JSON.stringify(next.pairs) === JSON.stringify(prev.pairs)
          if (!pairsSame || Date.now() < _snapshotDedupBypassUntil) positionSnapshot.value = next
        }

        if (msg.type === 'market_data' && msg.data) {
          const d = msg.data
          // Normalise field names from SpreadData model
          marketData.value = {
            binance_bid: d.binance_quote?.bid_price ?? d.binance_bid ?? 0,
            binance_ask: d.binance_quote?.ask_price ?? d.binance_ask ?? 0,
            binance_mid: d.binance_mid ?? ((d.binance_quote?.bid_price + d.binance_quote?.ask_price) / 2) ?? 0,
            binance_bid_qty: d.binance_quote?.bid_qty ?? 0,
            binance_ask_qty: d.binance_quote?.ask_qty ?? 0,
            bybit_bid: d.bybit_quote?.bid_price ?? d.bybit_bid ?? 0,
            bybit_ask: d.bybit_quote?.ask_price ?? d.bybit_ask ?? 0,
            bybit_mid: d.bybit_mid ?? ((d.bybit_quote?.bid_price + d.bybit_quote?.ask_price) / 2) ?? 0,
            bybit_bid_qty: d.bybit_quote?.bid_qty ?? 0,
            bybit_ask_qty: d.bybit_quote?.ask_qty ?? 0,
            timestamp: d.timestamp,
          }
        }
        // Rust Engine sends type:"spread" with both Binance+Bybit prices every 500ms
        else if (msg.type === 'spread' && msg.data) {
          const d = msg.data
          marketData.value = {
            binance_bid: d.binance_bid ?? 0,
            binance_ask: d.binance_ask ?? 0,
            binance_mid: d.binance_bid != null ? (d.binance_bid + d.binance_ask) / 2 : 0,
            binance_bid_qty: d.binance_bid_qty ?? 0,
            binance_ask_qty: d.binance_ask_qty ?? 0,
            bybit_bid:   d.bybit_bid   ?? 0,
            bybit_ask:   d.bybit_ask   ?? 0,
            bybit_mid:   d.bybit_bid   != null ? (d.bybit_bid + d.bybit_ask) / 2 : 0,
            bybit_bid_qty: d.bybit_bid_qty ?? 0,
            bybit_ask_qty: d.bybit_ask_qty ?? 0,
            timestamp:   d.timestamp,
          }
        }
        // Go TickPusher: 250ms Binance-only tick — merge into marketData
        else if (msg.type === 'tick' && msg.data) {
          const d = msg.data
          const prev = marketData.value
          marketData.value = {
            binance_bid: d.bid_price ?? prev?.binance_bid ?? 0,
            binance_ask: d.ask_price ?? prev?.binance_ask ?? 0,
            binance_mid: d.bid_price != null ? (d.bid_price + d.ask_price) / 2 : (prev?.binance_mid ?? 0),
            binance_bid_qty: prev?.binance_bid_qty ?? 0,
            binance_ask_qty: prev?.binance_ask_qty ?? 0,
            bybit_bid: prev?.bybit_bid ?? 0,
            bybit_ask: prev?.bybit_ask ?? 0,
            bybit_mid: prev?.bybit_mid ?? 0,
            bybit_bid_qty: prev?.bybit_bid_qty ?? 0,
            bybit_ask_qty: prev?.bybit_ask_qty ?? 0,
            timestamp: d.timestamp ?? prev?.timestamp,
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

      // For other close reasons, reconnect quickly
      reconnectTimer = setTimeout(connect, 500)
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

  // Force a full reconnect — used on user switch so the new JWT is used.
  // Token is re-read from localStorage inside connect().
  function reconnect() {
    disconnect()
    token = null  // force getToken() to re-read fresh token
    positionSnapshot.value = {
      bybit_long_lots: 0,
      bybit_short_lots: 0,
      binance_long_xau: 0,
      binance_short_xau: 0,
      pairs: {},
    }
    connect()
  }

  // Keep fetchMarketData for any legacy callers — returns last known data
  function fetchMarketData() {
    return Promise.resolve(marketData.value)
  }

  // Request an immediate position snapshot from the backend (bypasses 30s broadcast cycle)
  function requestSnapshot() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      _snapshotDedupBypassUntil = Date.now() + 10000
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
    marketRates,
    quoteDivergence,
    marketData,
    accountBalanceData,
    connected,
    lastMessage,
    strategyMessage,
    positionSnapshot,
    connect,
    disconnect,
    reconnect,
    fetchMarketData,
    requestSnapshot,
  }
})
