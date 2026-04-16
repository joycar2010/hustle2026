import { ref, onUnmounted } from 'vue'

/**
 * WebSocket composable for www.hustle2026.xyz
 * Connects to Go WS hub, receives account_balance pushes.
 * Auto-reconnects with exponential backoff.
 */
export function useWebSocket() {
  const connected = ref(false)
  const lastMessage = ref(null)

  let ws = null
  let reconnectTimer = null
  let reconnectDelay = 1000
  let intentionalClose = false

  function getWsUrl() {
    const token = localStorage.getItem('www_token')
    if (!token) return null
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/api/v1/ws?token=${token}`
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return

    const url = getWsUrl()
    if (!url) return

    intentionalClose = false

    try {
      ws = new WebSocket(url)
    } catch { return }

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000
      // Request account balance data
      ws.send(JSON.stringify({ type: 'request_snapshot' }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        lastMessage.value = msg
      } catch { /* ignore non-JSON */ }
    }

    ws.onclose = () => {
      connected.value = false
      ws = null
      if (!intentionalClose) scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will fire after onerror
    }
  }

  function disconnect() {
    intentionalClose = true
    clearTimeout(reconnectTimer)
    if (ws) {
      ws.close()
      ws = null
    }
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

  onUnmounted(() => disconnect())

  return { connected, lastMessage, connect, disconnect, send }
}
