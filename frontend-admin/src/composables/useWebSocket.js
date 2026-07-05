import { ref, onUnmounted } from 'vue'

/**
 * WebSocket composable for admin.hustle2026.xyz
 * Connects to Go WS hub, receives real-time push data.
 */
export function useWebSocket() {
  const connected = ref(false)
  const lastMessage = ref(null)
  const messageCount = ref(0)

  let ws = null
  let reconnectTimer = null
  let reconnectDelay = 1000
  let intentionalClose = false
  let connectedAt = null
  let deadTimer = null
  let _hooked = false

  function getWsUrl() {
    const token = localStorage.getItem('admin_token')
    if (!token) return null
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/api/v1/ws?token=${token}`
  }

  // 数据活性看门狗:Rust Hub 每≤3.5s 推一帧;静默 >20s 判半开假死 → close 触发重连。
  function _armDead() {
    if (deadTimer) clearTimeout(deadTimer)
    deadTimer = setTimeout(() => { try { ws && ws.close() } catch (_) {} }, 20000)
  }
  function _clearDead() { if (deadTimer) { clearTimeout(deadTimer); deadTimer = null } }

  // 聚焦/联网自愈:回前台/联网,断了立即重连(清退避),连着则补探活性。
  function _wake() {
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      reconnectDelay = 1000
      clearTimeout(reconnectTimer)
      connect()
    } else if (ws.readyState === WebSocket.OPEN) {
      _armDead()
    }
  }
  function _onVisible() { if (document.visibilityState === 'visible') _wake() }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return
    const url = getWsUrl()
    if (!url) return
    intentionalClose = false
    if (!_hooked && typeof window !== 'undefined') {
      _hooked = true
      document.addEventListener('visibilitychange', _onVisible)
      window.addEventListener('online', _wake)
    }
    try { ws = new WebSocket(url) } catch { return }

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000
      connectedAt = Date.now()
      _armDead()
      ws.send(JSON.stringify({ type: 'request_snapshot' }))
    }
    ws.onmessage = (event) => {
      _armDead()
      try {
        const msg = JSON.parse(event.data)
        messageCount.value++
        lastMessage.value = msg
      } catch {}
    }
    ws.onclose = () => {
      connected.value = false
      ws = null
      _clearDead()
      if (!intentionalClose) scheduleReconnect()
    }
    ws.onerror = () => {}
  }

  function disconnect() {
    intentionalClose = true
    _clearDead()
    if (_hooked) {
      document.removeEventListener('visibilitychange', _onVisible)
      window.removeEventListener('online', _wake)
      _hooked = false
    }
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
    if (ws && ws.readyState === WebSocket.OPEN)
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
  }

  function getUptime() {
    if (!connectedAt || !connected.value) return '--'
    const sec = Math.floor((Date.now() - connectedAt) / 1000)
    if (sec < 60) return sec + 's'
    if (sec < 3600) return Math.floor(sec / 60) + 'm' + (sec % 60) + 's'
    return Math.floor(sec / 3600) + 'h' + Math.floor((sec % 3600) / 60) + 'm'
  }

  onUnmounted(() => disconnect())

  return { connected, lastMessage, messageCount, connect, disconnect, send, getUptime }
}
