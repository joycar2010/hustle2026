import { useEffect, useRef, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { useSpreadStore } from '@/stores/spreadStore'
import { useEngineStore } from '@/stores/engineStore'
import { useBalanceStore } from '@/stores/balanceStore'
import { useBanStore } from '@/stores/banStore'
import { useSymbolStatusStore } from '@/stores/symbolStatusStore'
import { useMarketDataStore } from '@/stores/marketDataStore'
import { useUiStore } from '@/stores/uiStore'

const RECONNECT_BASE = 1000
const RECONNECT_MAX = 15000
const RECONNECT_LIMIT = 50
const PING_INTERVAL = 30000

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectDelay = useRef(RECONNECT_BASE)
  const pingTimer = useRef<ReturnType<typeof setInterval>>(undefined)
  const pingSentAt = useRef<number>(0)
  const token = useAuthStore((s) => s.token)
  const setBulk = useSpreadStore((s) => s.setBulk)
  const updateWorkerFromWs = useEngineStore((s) => s.updateWorkerFromWs)
  const setBalances = useBalanceStore((s) => s.setBalances)
  const setSummary = useBalanceStore((s) => s.setSummary)
  const setWsLatency = useBalanceStore((s) => s.setWsLatency)
  const setBans = useBanStore((s) => s.setBans)
  const setSymbolStatuses = useSymbolStatusStore((s) => s.setStatuses)
  const setMarketData = useMarketDataStore((s) => s.setMarketData)

  const connect = useCallback(() => {
    if (!token) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = window.location.host
    const url = `${proto}://${host}/ws/stream?token=${token}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectDelay.current = RECONNECT_BASE
      useUiStore.getState().setWsConnected(true)
      useUiStore.getState().resetWsReconnectCount()
      useUiStore.getState().setWsLastConnectedAt(Date.now())
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          pingSentAt.current = Date.now()
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL)
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
          case 'market_data':
            if (msg.data) {
              setMarketData(msg.data)
            }
            break
          case 'notification':
            window.dispatchEvent(new CustomEvent('ws:notification', { detail: msg.data }))
            break
          case 'pushed_update':
            // 推送列表变化(任意来源:本页/其它页/外部)→ 通知 dashboard 实时刷新
            window.dispatchEvent(new CustomEvent('pushed:refresh', { detail: msg.data }))
            break
          case 'pong':
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
      if (pingTimer.current) clearInterval(pingTimer.current)
      useUiStore.getState().setWsConnected(false)
      const count = useUiStore.getState().wsReconnectCount
      if (count >= RECONNECT_LIMIT) return
      useUiStore.getState().incrementWsReconnectCount()
      setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, RECONNECT_MAX)
        connect()
      }, reconnectDelay.current)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [token, setBulk, updateWorkerFromWs, setBalances, setSummary, setWsLatency, setBans, setSymbolStatuses, setMarketData])

  useEffect(() => {
    connect()

    const manualHandler = () => {
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
      reconnectDelay.current = RECONNECT_BASE
      connect()
    }
    window.addEventListener('ws:manual-reconnect', manualHandler)

    return () => {
      window.removeEventListener('ws:manual-reconnect', manualHandler)
      if (pingTimer.current) clearInterval(pingTimer.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
    }
  }, [connect])
}
