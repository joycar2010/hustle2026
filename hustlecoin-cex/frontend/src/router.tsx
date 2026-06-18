import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginPage } from '@/pages/LoginPage'
import { AuthGuard } from '@/components/layout/AuthGuard'

// 路由级代码分割:各页面懒加载,弱网首屏只下当前页(LoginPage 首屏必需,保持静态)
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then(m => ({ default: m.DashboardPage })))
const SpreadsPage = lazy(() => import('@/pages/SpreadsPage').then(m => ({ default: m.SpreadsPage })))
const HistoryPage = lazy(() => import('@/pages/HistoryPage').then(m => ({ default: m.HistoryPage })))
const RulesPage = lazy(() => import('@/pages/RulesPage').then(m => ({ default: m.RulesPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then(m => ({ default: m.SettingsPage })))
const BlacklistPage = lazy(() => import('@/pages/BlacklistPage').then(m => ({ default: m.BlacklistPage })))
const AccountsPage = lazy(() => import('@/pages/AccountsPage').then(m => ({ default: m.AccountsPage })))
const CoinManagementPage = lazy(() => import('@/pages/CoinManagementPage').then(m => ({ default: m.CoinManagementPage })))

function lazyPage(node: React.ReactNode) {
  return <Suspense fallback={<div className="p-6 text-center text-xs text-muted-foreground">加载中...</div>}>{node}</Suspense>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: (
      <AuthGuard>
        <AppLayout />
      </AuthGuard>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: lazyPage(<DashboardPage />) },
      { path: 'spreads', element: lazyPage(<SpreadsPage />) },
      { path: 'history', element: lazyPage(<HistoryPage />) },
      { path: 'accounts', element: lazyPage(<AccountsPage />) },
      { path: 'rules', element: lazyPage(<RulesPage />) },
      { path: 'settings', element: lazyPage(<SettingsPage />) },
      { path: 'blacklist', element: lazyPage(<BlacklistPage />) },
      { path: 'coins', element: lazyPage(<CoinManagementPage />) },
    ],
  },
])
