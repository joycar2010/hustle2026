import { useEffect, useState } from 'react'
import { getIpipgoOrders, syncIpipgoOrders, type IpipgoOrder } from '@/api/admin'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToastStore } from '@/components/ui/toast'
import { RefreshCw } from 'lucide-react'

export function IpipgoPage() {
  const [orders, setOrders] = useState<IpipgoOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  const reload = () => {
    setLoading(true)
    getIpipgoOrders().then(setOrders).finally(() => setLoading(false))
  }

  useEffect(reload, [])

  const handleSync = async () => {
    setSyncing(true)
    try {
      const result = await syncIpipgoOrders()
      addToast(`同步完成: ${result.synced} 个订单`, 'success')
      reload()
    } catch {
      addToast('同步失败', 'error')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">IPIPGO 订单</h1>
        <Button size="sm" onClick={handleSync} disabled={syncing}>
          <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
          {syncing ? '同步中...' : '同步订单'}
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3">订单号</th>
                <th className="px-4 py-3">产品</th>
                <th className="px-4 py-3">IP</th>
                <th className="px-4 py-3">协议</th>
                <th className="px-4 py-3">区域</th>
                <th className="px-4 py-3">到期时间</th>
                <th className="px-4 py-3">剩余天数</th>
                <th className="px-4 py-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : orders.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">暂无订单，请点击"同步订单"拉取</td></tr>
              ) : (
                orders.map((o) => (
                  <tr key={o.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 font-mono text-xs">{o.order_no}</td>
                    <td className="px-4 py-3">{o.product_name || '-'}</td>
                    <td className="px-4 py-3 font-mono text-xs">{o.ip_address ? `${o.ip_address}:${o.port}` : '-'}</td>
                    <td className="px-4 py-3">{o.protocol || '-'}</td>
                    <td className="px-4 py-3">{o.region || '-'}</td>
                    <td className="px-4 py-3">{o.end_date ? new Date(o.end_date).toLocaleDateString('zh-CN') : '-'}</td>
                    <td className="px-4 py-3">
                      {o.days_left !== null ? (
                        <span className={o.days_left <= 7 ? 'text-negative font-medium' : o.days_left <= 30 ? 'text-warning' : 'text-positive'}>
                          {o.days_left} 天
                        </span>
                      ) : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={o.status === 'active' ? 'success' : o.status === 'expired' ? 'destructive' : 'secondary'}>
                        {o.status}
                      </Badge>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
