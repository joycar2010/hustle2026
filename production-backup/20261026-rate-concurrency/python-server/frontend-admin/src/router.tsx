import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AdminLayout } from '@/components/layout/AdminLayout'
import { AuthGuard } from '@/components/layout/AuthGuard'
import { LoginPage } from '@/pages/LoginPage'

// 路由级代码分割:各页面懒加载,弱网首屏只下当前页(LoginPage 首屏必需,保持静态)
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then(m => ({ default: m.DashboardPage })))
const UsersPage = lazy(() => import('@/pages/UsersPage').then(m => ({ default: m.UsersPage })))
const GlobalRulesPage = lazy(() => import('@/pages/GlobalRulesPage').then(m => ({ default: m.GlobalRulesPage })))
const MarketMonitorPage = lazy(() => import('@/pages/MarketMonitorPage').then(m => ({ default: m.MarketMonitorPage })))
const NotifyPage = lazy(() => import('@/pages/NotifyPage').then(m => ({ default: m.NotifyPage })))
const SystemPage = lazy(() => import('@/pages/SystemPage').then(m => ({ default: m.SystemPage })))
const AiSupportPage = lazy(() => import('@/pages/AiSupportPage').then(m => ({ default: m.AiSupportPage })))
const CoinManagementPage = lazy(() => import('@/pages/CoinManagementPage').then(m => ({ default: m.CoinManagementPage })))
const HistoryPage = lazy(() => import('@/pages/HistoryPage').then(m => ({ default: m.HistoryPage })))
const FundsPage = lazy(() => import('@/pages/FundsPage').then(m => ({ default: m.FundsPage })))

function lazyPage(node: React.ReactNode) {
  return <Suspense fallback={<div className="p-6 text-center text-xs text-muted-foreground">加载中...</div>}>{node}</Suspense>
}

export const router = createBrowserRouter([
  {
    path: '/admin/login',
    element: <LoginPage />,
  },
  {
    path: '/admin',
    element: (
      <AuthGuard>
        <AdminLayout />
      </AuthGuard>
    ),
    children: [
      { index: true, element: <Navigate to="/admin/dashboard" replace /> },
      { path: 'dashboard', element: lazyPage(<DashboardPage />) },
      { path: 'users', element: lazyPage(<UsersPage />) },
      { path: 'funds', element: lazyPage(<FundsPage />) },
      { path: 'history', element: lazyPage(<HistoryPage />) },
      { path: 'global-rules', element: lazyPage(<GlobalRulesPage />) },
      { path: 'coins', element: lazyPage(<CoinManagementPage />) },
      { path: 'market-monitor', element: lazyPage(<MarketMonitorPage />) },
      { path: 'notifications', element: lazyPage(<NotifyPage />) },
      { path: 'system', element: lazyPage(<SystemPage />) },
      { path: 'ai-support', element: lazyPage(<AiSupportPage />) },
    ],
  },
])
