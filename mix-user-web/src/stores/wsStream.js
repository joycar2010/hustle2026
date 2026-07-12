// wsStream pinia store — channel-based WS subscriber.
// Token key is injected by each site (go/www/auto) via param.
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'

const TOKEN_KEY = 'www_token'

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/v1/ws`
}

export const useWsStream = defineStore('wsStream', () => {
  const connected = ref(false)
  const channels = reactive({})
  const subs = new Set()
  let socket = null
  let reconnectAttempts = 0
  let reconnectTimer = null
  let pingTimer = null
  let deadTimer = null

  function _reconnect() {
    if (reconnectTimer) return
    const wait = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts)) * (0.8 + Math.random() * 0.4)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect() }, wait)
  }

  // 数据活性看门狗:Rust Hub 对每个连接无条件每≤3.5s 推一帧;静默 >20s 即判半开假死 → 主动 close 触发重连。
  // (服务端不回应用层 pong,故以"入站消息活性"判活,而非等 pong。)
  function _armDead() {
    if (deadTimer) clearTimeout(deadTimer)
    deadTimer = setTimeout(() => { try { socket && socket.close() } catch (_) {} }, 20000)
  }
  function _clearDead() { if (deadTimer) { clearTimeout(deadTimer); deadTimer = null } }

  // 聚焦/联网自愈:回前台或网络恢复时,已断则立即重连(清退避),仍连着则补探一次活性。
  function _wake() {
    if (!socket || socket.readyState === WebSocket.CLOSED || socket.readyState === WebSocket.CLOSING) {
      reconnectAttempts = 0
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
      connect()
    } else if (socket.readyState === WebSocket.OPEN) {
      _armDead()
      try { socket.send(JSON.stringify({ type: 'ping', t: Date.now() })) } catch (_) {}
    }
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return
    try { socket = new WebSocket(`${wsUrl()}?token=${encodeURIComponent(token)}`) }
    catch (e) { _reconnect(); return }

    socket.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
      _armDead()
      for (const ch of subs) socket.send(JSON.stringify({ type: 'subscribe', channel: ch }))
      if (pingTimer) clearInterval(pingTimer)
      pingTimer = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          try { socket.send(JSON.stringify({ type: 'ping', t: Date.now() })) } catch (_) {}
        }
      }, 25000)
    }
    socket.onmessage = (ev) => {
      _armDead()
      let m; try { m = JSON.parse(ev.data) } catch (_) { return }
      // Python stream 格式（兼容旧协议）
      if (m.type === 'stream' && m.channel) { channels[m.channel] = m.payload; return }
      // Rust Hub 格式：type 即频道名，data 为 payload
      if (m.type && m.data !== undefined &&
          m.type !== 'connection' && m.type !== 'pong') {
        channels[m.type] = m.data
      }
    }
    socket.onclose = () => {
      connected.value = false
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
      _clearDead()
      _reconnect()
    }
    socket.onerror = () => {}
  }

  function subscribe(channel) {
    if (!channel) return
    subs.add(channel)
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'subscribe', channel }))
    }
  }
  function unsubscribe(channel) {
    subs.delete(channel)
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'unsubscribe', channel }))
    }
  }
  function disconnect() {
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
    _clearDead()
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (socket) { try { socket.close() } catch (_) {} socket = null }
    connected.value = false
    subs.clear()
  }

  // 聚焦/联网自愈监听(store 单例,仅注册一次)
  if (typeof window !== 'undefined') {
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') _wake() })
    window.addEventListener('online', _wake)
  }

  return { connected, channels, connect, subscribe, unsubscribe, disconnect }
})
