// wsStream pinia store — channel-based WS subscriber.
// Token key is injected by each site (go/www/auto) via param.
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'

const TOKEN_KEY = 'admin_token'

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

  function _reconnect() {
    if (reconnectTimer) return
    const wait = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts)) * (0.8 + Math.random() * 0.4)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect() }, wait)
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
      for (const ch of subs) socket.send(JSON.stringify({ type: 'subscribe', channel: ch }))
      if (pingTimer) clearInterval(pingTimer)
      pingTimer = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          try { socket.send(JSON.stringify({ type: 'ping', t: Date.now() })) } catch (_) {}
        }
      }, 25000)
    }
    socket.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data) } catch (_) { return }
      if (m.type === 'stream' && m.channel) channels[m.channel] = m.payload
    }
    socket.onclose = () => {
      connected.value = false
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
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
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (socket) { try { socket.close() } catch (_) {} socket = null }
    connected.value = false
    subs.clear()
  }

  return { connected, channels, connect, subscribe, unsubscribe, disconnect }
})
