// Mix WS 客户端 —— 服务端 20s 应用层心跳；客户端看门狗 >60s 静默强制重连
// （半开假死课：心跳只 ping 不验响应会静默漏消息）。指数退避重连 1s→30s。
export function connectStream(onMessage) {
  let ws = null
  let timer = null
  let backoff = 1000
  let lastMsg = Date.now()
  let closed = false

  const apiBase = import.meta.env.VITE_MIX_API || ''
  const origin = /^https?:/.test(apiBase)
    ? apiBase.replace(/\/api\/v1\/?$/, '')
    : window.location.origin
  const url = origin.replace(/^http/, 'ws') + '/ws/stream?token=' +
    encodeURIComponent(localStorage.getItem('mix_token') || '')

  function open() {
    if (closed) return
    try { ws = new WebSocket(url) } catch { retry(); return }
    ws.onopen = () => { backoff = 1000; lastMsg = Date.now() }
    ws.onmessage = (e) => {
      lastMsg = Date.now()
      try { onMessage(JSON.parse(e.data)) } catch { /* 非 JSON 帧忽略 */ }
    }
    ws.onclose = () => retry()
    ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
  }
  function retry() {
    if (closed) return
    clearTimeout(timer)
    timer = setTimeout(open, backoff)
    backoff = Math.min(backoff * 2, 30000)
  }
  const watchdog = setInterval(() => {
    if (Date.now() - lastMsg > 60000 && ws && ws.readyState === WebSocket.OPEN) {
      ws.close() // 触发重连
    }
  }, 15000)

  open()
  return () => { closed = true; clearTimeout(timer); clearInterval(watchdog); try { ws && ws.close() } catch { /* noop */ } }
}
