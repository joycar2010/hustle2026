import { useEffect, useRef, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { useSpreadStore } from '@/stores/spreadStore'
import { useEngineStore } from '@/stores/engineStore'
import { useBalanceStore } from '@/stores/balanceStore'
import { useBanStore } from '@/stores/banStore'
import { useSymbolStatusStore } from '@/stores/symbolStatusStore'
import { useMarketDataStore } from '@/stores/marketDataStore'
import { useRestrictionStore } from '@/stores/restrictionStore'
import { useUiStore } from '@/stores/uiStore'

const RECONNECT_BASE = 1000
const RECONNECT_MAX = 15000
const PING_INTERVAL = 30000
const PONG_TIMEOUT = 10000   // 发出 ping 后 N ms 内无 pong → 判定半开假死,强制重连

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectDelay = useRef(RECONNECT_BASE)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const pingTimer = useRef<ReturnType<typeof setInterval>>(undefined)
  const pongTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const pingSentAt = useRef<number>(0)
  const stopped = useRef(false)   // 卸载/登出标记:置 true 后不再自动重连
  const seenNotif = useRef<Map<string, number>>(new Map())   // [第三梯队] 通知去重:sig → 收到时刻
  const token = useAuthStore((s) => s.token)
  const setBulk = useSpreadStore((s) => s.setBulk)
  const updateWorkerFromWs = useEngineStore((s) => s.updateWorkerFromWs)
  const setBalances = useBalanceStore((s) => s.setBalances)
  const setSummary = useBalanceStore((s) => s.setSummary)
  const setWsLatency = useBalanceStore((s) => s.setWsLatency)
  const setBans = useBanStore((s) => s.setBans)
  const setSymbolStatuses = useSymbolStatusStore((s) => s.setStatuses)
  const setMarketData = useMarketDataStore((s) => s.setMarketData)

  const clearHeartbeat = useCallback(() => {
    if (pingTimer.current) { clearInterval(pingTimer.current); pingTimer.current = undefined }
    if (pongTimer.current) { clearTimeout(pongTimer.current); pongTimer.current = undefined }
  }, [])

  // 发一次 ping 并武装 pong 看门狗:超时未回 pong → 连接已死(半开),关闭以触发重连。
  const sendPing = useCallback((ws: WebSocket) => {
    if (ws.readyState !== WebSocket.OPEN) return
    pingSentAt.current = Date.now()
    try { ws.send(JSON.stringify({ type: 'ping' })) } catch { return }
    if (pongTimer.current) clearTimeout(pongTimer.current)
    pongTimer.current = setTimeout(() => {
      try { ws.close() } catch { /* onclose 会触发重连 */ }
    }, PONG_TIMEOUT)
  }, [])

  const connect = useCallback(() => {
    // 防重复建连:已有 OPEN/CONNECTING 连接则跳过
    const cur = wsRef.current
    if (cur && (cur.readyState === WebSocket.OPEN || cur.readyState === WebSocket.CONNECTING)) return
    // [修4] 始终用 localStorage 里的最新 token(axios 续期写的也是它),避免重连复用闭包旧 token
    const tk = localStorage.getItem('cex_jwt_token')
    if (!tk || stopped.current) return
    if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = undefined }

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = window.location.host
    const url = `${proto}://${host}/ws/stream?token=${tk}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectDelay.current = RECONNECT_BASE
      useUiStore.getState().setWsConnected(true)
      useUiStore.getState().resetWsReconnectCount()
      useUiStore.getState().setWsLastConnectedAt(Date.now())
      clearHeartbeat()
      pingTimer.current = setInterval(() => sendPing(ws), PING_INTERVAL)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'spread_snapshot':
          case 'spread_batch':
            setBulk(msg.data)
            break
          case 'position_update':
            window.dispatchEvent(new CustomEvent('ws:position', { detail: msg.data }))
            break
          case 'worker_status':
            updateWorkerFromWs(msg.data)
            break
          case 'balance_update':
            if (msg.data?.balances) {
              setBalances(msg.data.balances)
            }
            if (msg.data?.position_count !== undefined) {
              setSummary({
                positionCount: msg.data.position_count,
                totalContracts: msg.data.total_contracts ?? 0,
                masterFuturesPositions: msg.data.master_futures_positions ?? {},
                masterFuturesLiqPct: msg.data.master_futures_liq_pct ?? null,
              })
            }
            break
          case 'ban_update':
            if (msg.data?.sub_account_id && msg.data?.bans) {
              setBans(msg.data.sub_account_id, msg.data.bans)
            }
            break
          case 'symbol_status':
            if (msg.data?.sub_account_id && msg.data?.statuses) {
              setSymbolStatuses(msg.data.sub_account_id, msg.data.statuses)
            }
            break
          case 'account_restriction':
            // 逐子账户"被币安API限制"(restriction=null 表示解除)
            if (msg.data?.sub_account_id != null) {
              useRestrictionStore.getState().setRestriction(msg.data.sub_account_id, msg.data.restriction)
            }
            break
          case 'market_data':
            if (msg.data) {
              setMarketData(msg.data)
            }
            break
          case 'notification': {
            // [第三梯队] 推送去重:慢网频繁重连时服务端可能重投近期通知 → 60s 窗口内同一通知只弹一次。
            // 优先按通知 id 去重;无 id 则用内容签名(含服务端时间戳的真重投签名一致,新通知签名不同)。
            const d = msg.data ?? {}
            const sig = d.id != null ? `id:${d.id}` : `b:${JSON.stringify(d)}`
            const now = Date.now()
            const seen = seenNotif.current
            if (seen.size > 200) seen.clear()   // 兜底防无界增长
            for (const [k, ts] of seen) { if (now - ts > 60000) seen.delete(k) }
            if (seen.has(sig)) break   // 60s 内重复 → 丢弃
            seen.set(sig, now)
            window.dispatchEvent(new CustomEvent('ws:notification', { detail: msg.data }))
            break
          }
          case 'pushed_update':
            // 推送列表变化(任意来源:本页/其它页/外部)→ 通知 dashboard 实时刷新
            window.dispatchEvent(new CustomEvent('pushed:refresh', { detail: msg.data }))
            break
          case 'pong':
            // [修1] 收到 pong → 撤销看门狗,记录延迟
            if (pongTimer.current) { clearTimeout(pongTimer.current); pongTimer.current = undefined }
            if (pingSentAt.current > 0) {
              setWsLatency(Date.now() - pingSentAt.current)
            }
            break
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onclose = () => {
      clearHeartbeat()
      useUiStore.getState().setWsConnected(false)
      if (stopped.current) return
      // [修5] 去掉 50 次硬上限:退避封顶后恒定重试,绝不永久放弃(计数仅作展示/遥测)
      useUiStore.getState().incrementWsReconnectCount()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, RECONNECT_MAX)
        connect()
      }, reconnectDelay.current)
    }

    ws.onerror = () => {
      try { ws.close() } catch { /* onclose 会触发重连 */ }
    }
  }, [clearHeartbeat, sendPing, setBulk, updateWorkerFromWs, setBalances, setSummary, setWsLatency, setBans, setSymbolStatuses, setMarketData])

  useEffect(() => {
    stopped.current = false
    connect()

    const manualHandler = () => {
      reconnectDelay.current = RECONNECT_BASE
      useUiStore.getState().resetWsReconnectCount()
      if (wsRef.current) { wsRef.current.onclose = null; try { wsRef.current.close() } catch { /* */ } ; wsRef.current = null }
      connect()
    }

    // [修2] 回到前台 / 网络恢复 → 主动自愈:
    //   连接已断 → 立即重连(重置退避);连接仍 OPEN → 立刻 ping+看门狗,快速揪出半开假死。
    const revive = () => {
      if (document.visibilityState !== 'visible') return
      const cur = wsRef.current
      if (!cur || cur.readyState === WebSocket.CLOSED || cur.readyState === WebSocket.CLOSING) {
        reconnectDelay.current = RECONNECT_BASE
        connect()
      } else if (cur.readyState === WebSocket.OPEN) {
        sendPing(cur)
      }
    }

    window.addEventListener('ws:manual-reconnect', manualHandler)
    window.addEventListener('online', revive)
    document.addEventListener('visibilitychange', revive)

    return () => {
      stopped.current = true
      window.removeEventListener('ws:manual-reconnect', manualHandler)
      window.removeEventListener('online', revive)
      document.removeEventListener('visibilitychange', revive)
      if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = undefined }
      clearHeartbeat()
      if (wsRef.current) { wsRef.current.onclose = null; try { wsRef.current.close() } catch { /* */ } ; wsRef.current = null }
    }
  }, [connect, clearHeartbeat, sendPing, token])
}
