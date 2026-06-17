import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AdminLayout } from '@/components/layout/AdminLayout'
import { AuthGuard } from '@/components/layout/AuthGuard'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { UsersPage } from '@/pages/UsersPage'
import { GlobalRulesPage } from '@/pages/GlobalRulesPage'
import { MarketMonitorPage } from '@/pages/MarketMonitorPage'
import { NotifyPage } from '@/pages/NotifyPage'
import { SystemPage } from '@/pages/SystemPage'
import { AiSupportPage } from '@/pages/AiSupportPage'
import { CoinManagementPage } from '@/pages/CoinManagementPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { FundsPage } from '@/pages/FundsPage'

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
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'users', element: <UsersPage /> },
      { path: 'funds', element: <FundsPage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'global-rules', element: <GlobalRulesPage /> },
      { path: 'coins', element: <CoinManagementPage /> },
      { path: 'market-monitor', element: <MarketMonitorPage /> },
      { path: 'notifications', element: <NotifyPage /> },
      { path: 'system', element: <SystemPage /> },
      { path: 'ai-support', element: <AiSupportPage /> },
    ],
  },
])
