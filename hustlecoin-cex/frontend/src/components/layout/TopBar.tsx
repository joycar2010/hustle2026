import { LogOut, Activity } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useEngineStore } from '@/stores/engineStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function TopBar() {
  const username = useAuthStore((s) => s.username)
  const logout = useAuthStore((s) => s.logout)
  const engineStatus = useEngineStore((s) => s.status)

  return (
    <header className="flex h-14 items-center justify-between border-b bg-card px-4">
      <div className="flex items-center gap-3">
        <Activity size={16} className="text-muted-foreground" />
        <span className="text-sm text-muted-foreground">引擎状态</span>
        <Badge
          className={cn(
            engineStatus === 'RUNNING'
              ? 'bg-positive/20 text-positive border-positive/30'
              : 'bg-negative/20 text-negative border-negative/30',
          )}
        >
          {engineStatus === 'RUNNING' ? '运行中' : '已停止'}
        </Badge>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">{username}</span>
        <Button variant="ghost" size="icon" onClick={logout} title="退出登录">
          <LogOut size={16} />
        </Button>
      </div>
    </header>
  )
}
