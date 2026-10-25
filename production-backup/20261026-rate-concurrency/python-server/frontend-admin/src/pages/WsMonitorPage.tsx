import { useState, useCallback, useRef, useEffect } from 'react'
import { getWsStats, type WsStats } from '@/api/admin'
import { useAutoRefresh } from '@/hooks/useAutoRefresh'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { useAuthStore } from '@/stores/authStore'
import {
  Wifi, WifiOff, Activity, Clock, MessageSquare, Users,
  Zap, Radio,
} from 'lucide-react'

interface WsMessage {
  type: string
  data: unknown
  ts: number
}

export function WsMonitorPage() {
  const [stats, setStats] = useState<WsStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [connected, setConnected] = useState(false)
  const [messages, setMessages] = useState<WsMessage[]>([])
  const [msgCount, setMsgCount] = useState(0)
  const [connectTime, setConnectTime] = useState<Date | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const token = useAuthStore((s) => s.token)
  const addToast = useToastStore((s) => s.addToast)

  const fetchStats = useCallback(async () => {
    try {
      const data = await getWsStats()
      setStats(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useAutoRefresh(fetchStats, 10000)

  const connect = () => {
    if (wsRef.current) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/stream?token=${token}`)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setConnectTime(new Date())
      setMsgCount(0)
      setMessages([])
      addToast('WebSocket 已连接', 'success')
    }

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        setMsgCount(c => c + 1)
        setMessages(prev => [{ type: data.type || 'unknown', data, ts: Date.now() }, ...prev].slice(0, 50))
      } catch {}
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
    }

    ws.onerror = () => {
      addToast('WebSocket 连接失败', 'error')
    }
  }

  const disconnect = () => {
    wsRef.current?.close()
    wsRef.current = null
    setConnected(false)
  }

  useEffect(() => {
    return () => { wsRef.current?.close() }
  }, [])

  const uptimeStr = connectTime
    ? `${Math.floor((Date.now() - connectTime.getTime()) / 1000)}s`
    : '-'
  const msgRate = connectTime
    ? (msgCount / Math.max(1, (Date.now() - connectTime.getTime()) / 1000)).toFixed(1)
    : '0'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">WS 监控</h1>
        <div className="flex gap-2">
          {connected ? (
            <Button size="sm" variant="destructive" onClick={disconnect}>
              <WifiOff className="h-4 w-4" /> 断开
            </Button>
          ) : (
            <Button size="sm" onClick={connect}>
              <Wifi className="h-4 w-4" /> 连接
            </Button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard icon={MessageSquare} label="消息总数" value={String(msgCount)} />
        <StatCard icon={Clock} label="连接时长" value={uptimeStr} />
        <StatCard icon={Zap} label="消息速率" value={`${msgRate}/s`} />
        <StatCard icon={Users} label="服务端连接数" value={String(stats?.connections ?? 0)} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Server Streamers */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Radio className="h-4 w-4 text-primary" />
              推流服务状态
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-sm text-muted-foreground">加载中...</p>
            ) : !stats?.streamers.length ? (
              <p className="text-sm text-muted-foreground">无推流服务</p>
            ) : (
              <div className="space-y-2">
                {stats.streamers.map((s) => (
                  <div key={s.name} className="flex items-center justify-between text-sm">
                    <span className="font-medium">{s.name}</span>
                    <div className="flex items-center gap-2">
                      <Badge variant={s.status === 'active' ? 'success' : s.status === 'error' ? 'destructive' : 'secondary'}>
                        {s.status}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{s.interval}s</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Connection Status */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="h-4 w-4 text-primary" />
              连接信息
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">状态</span>
                <Badge variant={connected ? 'success' : 'secondary'}>
                  {connected ? '已连接' : '未连接'}
                </Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">服务端运行时长</span>
                <span>{stats ? `${Math.floor(stats.uptime_seconds / 3600)}h ${Math.floor((stats.uptime_seconds % 3600) / 60)}m` : '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">服务端总连接</span>
                <span>{stats?.connections ?? 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent Messages */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-primary" />
              最近消息
            </span>
            <Button size="sm" variant="ghost" onClick={() => setMessages([])}>
              清空
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {messages.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {connected ? '等待消息...' : '请先连接 WebSocket'}
            </p>
          ) : (
            <div className="max-h-80 overflow-y-auto space-y-1">
              {messages.map((m, i) => (
                <div key={i} className="flex items-start gap-2 rounded border-b border-border/50 py-1.5 text-xs last:border-0">
                  <Badge variant="outline" className="shrink-0">{m.type}</Badge>
                  <span className="text-muted-foreground shrink-0">{new Date(m.ts).toLocaleTimeString('zh-CN')}</span>
                  <span className="truncate font-mono text-[11px]">{JSON.stringify(m.data).slice(0, 120)}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function StatCard({ icon: Icon, label, value }: {
  icon: React.ComponentType<{ className?: string }>; label: string; value: string
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary/10 p-2">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-lg font-bold">{value}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
