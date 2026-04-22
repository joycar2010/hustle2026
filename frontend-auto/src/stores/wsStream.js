// frontend-auto wsStream pinia store — single WS connection, channel subs.
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'

const WS_URL = (() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/v1/ws`
})()

export const useWsStream = defineStore('wsStream', () => {
  const connected = ref(false)
  const lastError = ref('')
  const channels = reactive({})         // channel -> latest payload
  const subs = new Set()                // channel names subscribed
  let socket = null
  let reconnectAttempts = 0
  let reconnectTimer = null
  let pingTimer = null

  function _scheduleReconnect() {
    if (reconnectTimer) return
    const wait = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts)) * (0.8 + Math.random() * 0.4)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect() }, wait)
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return
    const token = localStorage.getItem('access_token')
    if (!token) { lastError.value = 'no_token'; return }
    try { socket = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`) }
    catch (e) { lastError.value = String(e); _scheduleReconnect(); return }

    socket.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
      lastError.value = ''
      // Re-subscribe all desired channels after reconnect
      for (const ch of subs) socket.send(JSON.stringify({ type: 'subscribe', channel: ch }))
      // Heartbeat
      if (pingTimer) clearInterval(pingTimer)
      pingTimer = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          try { socket.send(JSON.stringify({ type: 'ping', t: Date.now() })) } catch (_) {}
        }
      }, 25000)
    }

    socket.onmessage = (ev) => {
      let m
      try { m = JSON.parse(ev.data) } catch (_) { return }
      if (m.type === 'stream' && m.channel) {
        channels[m.channel] = m.payload
      } else if (m.type === 'error') {
        lastError.value = `${m.channel || ''}:${m.message || 'error'}`
      }
    }

    socket.onclose = () => {
      connected.value = false
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
      _scheduleReconnect()
    }

    socket.onerror = () => { /* close handler will trigger reconnect */ }
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

  return { connected, lastError, channels, connect, subscribe, unsubscribe, disconnect }
})
