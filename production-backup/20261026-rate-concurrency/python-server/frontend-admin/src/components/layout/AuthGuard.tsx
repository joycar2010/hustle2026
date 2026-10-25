import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

export function AuthGuard({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage)
  const navigate = useNavigate()
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    loadFromStorage()
    setLoaded(true)
  }, [loadFromStorage])

  useEffect(() => {
    if (loaded && !isAuthenticated) {
      navigate('/admin/login', { replace: true })
    }
    if (loaded && isAuthenticated && role !== 'SUPER_ADMIN' && role !== 'ADMIN') {
      logout()
      navigate('/admin/login?error=permission', { replace: true })
    }
  }, [loaded, isAuthenticated, role, navigate, logout])

  if (!loaded || !isAuthenticated) return null

  return <>{children}</>
}
