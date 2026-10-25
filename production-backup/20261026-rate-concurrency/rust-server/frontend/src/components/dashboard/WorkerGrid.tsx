import { Play, Square } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useEngineStore } from '@/stores/engineStore'
import { startWorker, stopWorker, startAllWorkers, stopAllWorkers } from '@/api/engine'
import { useToastStore } from '@/components/ui/toast'
import { cn } from '@/lib/utils'

export function WorkerGrid() {
  const workers = useEngineStore((s) => s.workers)
  const fetchWorkers = useEngineStore((s) => s.fetchWorkers)
  const addToast = useToastStore((s) => s.addToast)

  const handleStart = async (id: number) => {
    try {
      await startWorker(id)
      addToast('Worker 已启动', 'success')
      fetchWorkers()
    } catch {
      addToast('启动失败', 'error')
    }
  }

  const handleStop = async (id: number) => {
    try {
      await stopWorker(id)
      addToast('Worker 已停止', 'success')
      fetchWorkers()
    } catch {
      addToast('停止失败', 'error')
    }
  }

  const handleStartAll = async () => {
    try {
      await startAllWorkers()
      addToast('全部 Worker 已启动', 'success')
      fetchWorkers()
    } catch {
      addToast('批量启动失败', 'error')
    }
  }

  const handleStopAll = async () => {
    try {
      await stopAllWorkers()
      addToast('全部 Worker 已停止', 'success')
      fetchWorkers()
    } catch {
      addToast('批量停止失败', 'error')
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm">引擎 Workers</CardTitle>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleStartAll}>
            <Play size={14} /> 全部启动
          </Button>
          <Button size="sm" variant="outline" onClick={handleStopAll}>
            <Square size={14} /> 全部停止
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {workers.map((w) => (
            <div
              key={w.id}
              className="flex items-center justify-between rounded-md border bg-background p-3"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{w.account_note || `#${w.account_id}`}</span>
                  <Badge
                    className={cn(
                      'text-[10px]',
                      w.status === 'RUNNING'
                        ? 'bg-positive/20 text-positive border-positive/30'
                        : 'bg-negative/20 text-negative border-negative/30',
                    )}
                  >
                    {w.status === 'RUNNING' ? '运行中' : '已停止'}
                  </Badge>
                </div>
                <div className="flex gap-3 text-xs text-muted-foreground">
                  <span>持仓 {w.active_positions}</span>
                  <span>周期 {w.cycle_count}</span>
                </div>
              </div>
              {w.status === 'RUNNING' ? (
                <Button size="icon" variant="ghost" onClick={() => handleStop(w.id)}>
                  <Square size={14} className="text-negative" />
                </Button>
              ) : (
                <Button size="icon" variant="ghost" onClick={() => handleStart(w.id)}>
                  <Play size={14} className="text-positive" />
                </Button>
              )}
            </div>
          ))}
          {workers.length === 0 && (
            <p className="col-span-full text-center text-sm text-muted-foreground py-4">
              暂无 Worker 数据
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
