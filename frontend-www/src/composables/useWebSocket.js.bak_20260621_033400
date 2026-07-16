import { ref, reactive, onUnmounted } from 'vue'

/**
 * Enhanced WebSocket composable for www.hustle2026.xyz
 * Supports: account_balance push, request_data (PnL/FundFlow), typed handlers.
 * Auto-reconnects with exponential backoff.
 */
export function useWebSocket() {
  const connected = ref(false)
  const lastMessage = ref(null)
  const dataResponses = reactive({})
  const pending = reactive({})

  let ws = null
  let reconnectTimer = null
  let reconnectDelay = 1000
  let intentionalClose = false
  const _handlers = {}

  function getWsUrl() {
    const token = localStorage.getItem('www_token')
    if (!token) return null
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return proto + '//' + location.host + '/api/v1/ws?token=' + token
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return
    const url = getWsUrl()
    if (!url) return
    intentionalClose = false
    try { ws = new WebSocket(url) } catch { return }

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000
      ws.send(JSON.stringify({ type: 'request_snapshot' }))
      for (const [ch, params] of Object.entries(pending)) {
        ws.send(JSON.stringify({ type: 'request_data', channel: ch, params: params }))
      }
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        lastMessage.value = msg
        const msgType = msg.type
        if (msgType && msg.data !== undefined) {
          if (msgType === 'pnl_daily' || msgType === 'fund_flow') {
            dataResponses[msgType] = msg.data
            delete pending[msgType]
            if (_handlers[msgType]) {
              for (const fn of _handlers[msgType]) {
                try { fn(msg.data) } catch(e) { console.error('[WS] handler error:', e) }
              }
            }
          }
        }
      } catch { /* ignore non-JSON */ }
    }

    ws.onclose = () => {
      connected.value = false
      ws = null
      if (!intentionalClose) scheduleReconnect()
    }
    ws.onerror = () => {}
  }

  function disconnect() {
    intentionalClose = true
    clearTimeout(reconnectTimer)
    if (ws) { ws.close(); ws = null }
    connected.value = false
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 1.5, 15000)
      connect()
    }, reconnectDelay)
  }

  function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  /**
   * Request data via WebSocket. Returns Promise that resolves when data arrives
   * or rejects after timeout (caller can fallback to REST).
   */
  function requestData(channel, params, timeoutMs) {
    params = params || {}
    timeoutMs = timeoutMs || 8000
    return new Promise((resolve, reject) => {
      pending[channel] = params
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'request_data', channel: channel, params: params }))
      }
      let settled = false
      const timer = setTimeout(() => {
        if (!settled) { settled = true; reject(new Error('ws_timeout')) }
      }, timeoutMs)

      const handler = (data) => {
        if (!settled) { settled = true; clearTimeout(timer); resolve(data) }
      }
      if (!_handlers[channel]) _handlers[channel] = []
      _handlers[channel].push(handler)
      setTimeout(() => {
        const idx = (_handlers[channel] || []).indexOf(handler)
        if (idx >= 0) _handlers[channel].splice(idx, 1)
      }, timeoutMs + 1000)
    })
  }

  /**
   * Register a persistent handler for a channel type.
   * Returns unsubscribe function.
   */
  function onData(channel, callback) {
    if (!_handlers[channel]) _handlers[channel] = []
    _handlers[channel].push(callback)
    return () => {
      const idx = (_handlers[channel] || []).indexOf(callback)
      if (idx >= 0) _handlers[channel].splice(idx, 1)
    }
  }

  onUnmounted(() => disconnect())

  return { connected, lastMessage, dataResponses, connect, disconnect, send, requestData, onData }
}
