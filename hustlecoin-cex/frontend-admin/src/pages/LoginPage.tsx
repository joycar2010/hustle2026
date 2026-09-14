import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { initAdmin } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

export function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [searchParams] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(() => {
    if (searchParams.get('error') === 'permission') return '权限不足，仅管理员可登录管理后台'
    return ''
  })
  const [loading, setLoading] = useState(false)
  const [showInit, setShowInit] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      navigate('/admin/dashboard', { replace: true })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      if (msg?.includes('No admin') || msg?.includes('not found')) {
        setShowInit(true)
        setError('尚未初始化管理员账户')
      } else {
        setError(msg || '登录失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleInit = async () => {
    setError('')
    setLoading(true)
    try {
      await initAdmin(username, password)
      await login(username, password)
      navigate('/admin/dashboard', { replace: true })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || '初始化失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-[calc(100vw-2rem)] max-w-[380px]">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 w-20 h-20 flex items-center justify-center">
            <img src="/admin/logo.png" alt="HustleCoin" className="w-20 h-20 object-contain" />
          </div>
          <CardTitle className="text-xl">HustleCoin</CardTitle>
          <p className="text-sm text-muted-foreground">管理后台登录</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">用户名</label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" autoComplete="username" />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">密码</label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password" />
            </div>
            {error && <p className="text-sm text-negative">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? '登录中...' : '登录'}
            </Button>
            {showInit && (
              <Button type="button" variant="outline" className="w-full" onClick={handleInit} disabled={loading}>
                初始化管理员账户
              </Button>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
