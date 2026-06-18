import { useEffect, useState } from 'react'
import { listAuditLogs, type AuditLogItem } from '@/api/admin'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'

export function AuditPage() {
  const [logs, setLogs] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ user: '', action: '', resource: '', start_date: '', end_date: '' })

  const size = 50

  const reload = (p = page) => {
    setLoading(true)
    const params: Record<string, string | number | undefined> = { page: p, size }
    if (filters.user) params.user = filters.user
    if (filters.action) params.action = filters.action
    if (filters.resource) params.resource = filters.resource
    if (filters.start_date) params.start_date = filters.start_date
    if (filters.end_date) params.end_date = filters.end_date
    listAuditLogs(params)
      .then((d) => { setLogs(d.items); setTotal(d.total); setPage(d.page) })
      .finally(() => setLoading(false))
  }

  useEffect(() => reload(1), [])

  const totalPages = Math.ceil(total / size)

  const actionColor = (action: string) => {
    switch (action) {
      case 'CREATE': return 'success'
      case 'UPDATE': return 'warning'
      case 'DELETE': return 'destructive'
      default: return 'secondary' as const
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">审计日志</h1>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap gap-2">
            <Input className="w-full sm:w-32" placeholder="用户" value={filters.user} onChange={(e) => setFilters({ ...filters, user: e.target.value })} />
            <select
              className="flex h-9 rounded-md border border-input bg-transparent px-3 text-sm"
              value={filters.action}
              onChange={(e) => setFilters({ ...filters, action: e.target.value })}
            >
              <option value="">全部操作</option>
              <option value="CREATE">CREATE</option>
              <option value="UPDATE">UPDATE</option>
              <option value="DELETE">DELETE</option>
              <option value="LOGIN">LOGIN</option>
            </select>
            <Input className="w-full sm:w-40" placeholder="资源" value={filters.resource} onChange={(e) => setFilters({ ...filters, resource: e.target.value })} />
            <Input type="date" className="w-full sm:w-36" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} />
            <Input type="date" className="w-full sm:w-36" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} />
            <Button size="sm" onClick={() => reload(1)}>
              <Search className="h-4 w-4" /> 搜索
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full md:min-w-[700px] text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-4 py-3">时间</th>
                <th className="px-4 py-3">用户</th>
                <th className="px-4 py-3">操作</th>
                <th className="px-4 py-3">资源</th>
                <th className="px-4 py-3">详情</th>
                <th className="px-4 py-3">IP</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">加载中...</td></tr>
              ) : logs.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">暂无日志</td></tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : '-'}
                    </td>
                    <td className="px-4 py-3">{log.user}</td>
                    <td className="px-4 py-3">
                      <Badge variant={actionColor(log.action)}>{log.action}</Badge>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{log.resource}</td>
                    <td className="px-4 py-3 max-w-xs truncate text-muted-foreground" title={log.details || ''}>
                      {log.details || '-'}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{log.ip_address || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => reload(page - 1)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages} ({total} 条)</span>
          <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => reload(page + 1)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
