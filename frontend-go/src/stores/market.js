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
  let deadTimer = null
  let freshnessTimer = null
  let lastMarketDataAt = 0
  let lastMarketTimestamp = 0
  let restRefreshInFlight = false

  // 数据活性看门狗:Rust /ws 对每个连接每≤3.5s 推一帧;静默 >20s 判半开假死 → close 触发重连。
  // (服务端不回应用层 pong,故以"入站消息活性"判活,而非等 pong。)
  function _armDead() {
    if (deadTimer) clearTimeout(deadTimer)
    deadTimer = setTimeout(() => { try { ws && ws.close() } catch (_) {} }, 20000)
  }
  function _clearDead() { if (deadTimer) { clearTimeout(deadTimer); deadTimer = null } }
  // 聚焦/联网自愈:回前台/联网,断了立即重连,连着则补探活性。
  function _wake() {
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
      connect()
    } else if (ws.readyState === WebSocket.OPEN) {
      _armDead()
    }
  }

  function getToken() {
    return localStorage.getItem('token') || ''
  }

  function _finite(value, fallback = 0) {
    const n = Number(value)
    return Number.isFinite(n) ? n : fallback
  }

  function _markMarketFresh(sourceTimestamp) {
    const timestamp = Number(sourceTimestamp)
    if (!Number.isFinite(timestamp) || timestamp <= 0) {
      lastMarketDataAt = Date.now()
      return
    }
    if (timestamp > lastMarketTimestamp) {
      lastMarketTimestamp = timestamp
      lastMarketDataAt = Date.now()
    }
  }

  function _applyMarketData(data) {
    if (!data || data.error) return false
    const a = data.binance_quote || data.a_quote || {}
    const b = data.bybit_quote || data.b_quote || {}
    const binanceBid = _finite(a.bid_price ?? data.binance_bid)
    const binanceAsk = _finite(a.ask_price ?? data.binance_ask)
    const bybitBid = _finite(b.bid_price ?? data.bybit_bid)
    const bybitAsk = _finite(b.ask_price ?? data.bybit_ask)
    if (!binanceBid || !binanceAsk || !bybitBid || !bybitAsk) return false

    marketData.value = {
      binance_bid: binanceBid,
      binance_ask: binanceAsk,
      binance_mid: _finite(data.binance_mid, (binanceBid + binanceAsk) / 2),
      binance_bid_qty: _finite(a.bid_qty ?? data.binance_bid_qty),
      binance_ask_qty: _finite(a.ask_qty ?? data.binance_ask_qty),
      bybit_bid: bybitBid,
      bybit_ask: bybitAsk,
      bybit_mid: _finite(data.bybit_mid, (bybitBid + bybitAsk) / 2),
      bybit_bid_qty: _finite(b.bid_qty ?? data.bybit_bid_qty),
      bybit_ask_qty: _finite(b.ask_qty ?? data.bybit_ask_qty),
      timestamp: data.timestamp ?? Date.now(),
    }
    _markMarketFresh(data.timestamp)
    return true
  }

  async function _refreshMarketDataViaRest(force = false) {
    if (restRefreshInFlight) return
    if (!force && Date.now() - lastMarketDataAt < 6000) return
    restRefreshInFlight = true
    const requestedPair = currentPair.value || 'XAU'
    try {
      const authToken = getToken()
      const response = await fetch(`/api/v1/market/spread?pair=${encodeURIComponent(requestedPair)}`, {
        cache: 'no-store',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      })
      if (!response.ok) return
      const data = await response.json()
      if (currentPair.value === requestedPair) _applyMarketData(data)
    } catch (_) {
      // WebSocket remains the primary path; the next watchdog pass retries REST.
    } finally {
      restRefreshInFlight = false
    }
  }

  function _ensureFreshnessWatch() {
    if (freshnessTimer) return
    freshnessTimer = setInterval(() => _refreshMarketDataViaRest(false), 2000)
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
    console.log('[WebSocket] Connecting to:', WS_URL)

    const socket = new WebSocket(url)
    ws = socket

    socket.onopen = () => {
      if (ws !== socket) {
        socket.close()
        return
      }
      console.log('[WebSocket] Connected successfully')
      connected.value = true
      _armDead()
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      // 连接成功后立即请求持仓快照，避免等待30s定时广播
      socket.send(JSON.stringify({ type: 'request_snapshot' }))
      // Subscribe to current trading pair room for per-pair market data
      const { currentPair } = useTradingPair()
      socket.send(JSON.stringify({ type: 'subscribe', pairs: [currentPair.value] }))
      _ensureFreshnessWatch()
      _refreshMarketDataViaRest(true)
    }

    socket.onmessage = (event) => {
      if (ws !== socket) return
      _armDead()
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
          _applyMarketData(msg.data)
        }
        // Rust Engine sends type:"spread" with both Binance+Bybit prices every 500ms
        else if (msg.type === 'spread' && msg.data) {
          _applyMarketData(msg.data)
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
          _markMarketFresh(d.timestamp)
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

    socket.onclose = (event) => {
      if (ws !== socket) return
      connected.value = false
      ws = null
      _clearDead()

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

    socket.onerror = () => {
      socket.close()
    }
  }

  function disconnect() {
    _clearDead()
    if (freshnessTimer) {
      clearInterval(freshnessTimer)
      freshnessTimer = null
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      const socket = ws
      ws = null
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      socket.close()
    }
    connected.value = false
  }

  // Force a full reconnect — used on user switch so the new JWT is used.
  // Token is re-read from localStorage inside connect().
  function reconnect() {
    const latestToken = getToken()
    if (ws && token === latestToken &&
        (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return
    }
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
  async function fetchMarketData() {
    await _refreshMarketDataViaRest(true)
    return marketData.value
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
    // 20260707: 切对即清空行情快照 — 否则新对无数据流时(如新建对Rust未重启/休市)
    // 页面会一直显示上一个对的残价(BTC页显示XAUUSDT金价实证), 错值比空值危险。
    marketData.value = null
    lastMarketDataAt = 0
    lastMarketTimestamp = 0
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (oldPair) ws.send(JSON.stringify({ type: 'unsubscribe', pairs: [oldPair] }))
      ws.send(JSON.stringify({ type: 'subscribe', pairs: [newPair] }))
    }
    _refreshMarketDataViaRest(true)
  })

  // 聚焦/联网自愈监听(store 单例,仅注册一次)
  if (typeof window !== 'undefined') {
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') _wake() })
    window.addEventListener('online', _wake)
  }

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
