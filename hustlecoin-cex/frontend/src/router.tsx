import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { SpreadsPage } from '@/pages/SpreadsPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { RulesPage } from '@/pages/RulesPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { BlacklistPage } from '@/pages/BlacklistPage'
import { AccountsPage } from '@/pages/AccountsPage'
import { CoinManagementPage } from '@/pages/CoinManagementPage'
import { AuthGuard } from '@/components/layout/AuthGuard'

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
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'spreads', element: <SpreadsPage /> },
      { path: 'history', element: <HistoryPage /> },
      { path: 'accounts', element: <AccountsPage /> },
      { path: 'rules', element: <RulesPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'blacklist', element: <BlacklistPage /> },
      { path: 'coins', element: <CoinManagementPage /> },
    ],
  },
])
