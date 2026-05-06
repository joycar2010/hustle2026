import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

export function AuthGuard({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage)
  const navigate = useNavigate()
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    loadFromStorage()
    setLoaded(true)
  }, [loadFromStorage])

  useEffect(() => {
    if (loaded && !isAuthenticated) {
      navigate('/login', { replace: true })
    }
  }, [loaded, isAuthenticated, navigate])

  if (!loaded || !isAuthenticated) return null

  return <>{children}</>
}
