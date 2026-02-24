import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    name: 'TradingDashboard',
    component: () => import('@/views/TradingDashboard.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/trading',
    name: 'Trading',
    component: () => import('@/views/Trading.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/pending-orders',
    name: 'PendingOrders',
    component: () => import('@/views/PendingOrders.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/strategies',
    name: 'Strategies',
    component: () => import('@/views/Strategies.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/positions',
    name: 'Positions',
    component: () => import('@/views/Positions.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/accounts',
    name: 'Accounts',
    component: () => import('@/views/Accounts.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/risk',
    name: 'Risk',
    component: () => import('@/views/Risk.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/system',
    name: 'System',
    component: () => import('@/views/System.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/test',
    name: 'BinanceTest',
    component: () => import('@/views/BinanceTest.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/test1',
    name: 'BybitTest',
    component: () => import('@/views/BybitTest.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/rbac',
    name: 'RbacManagement',
    component: () => import('@/views/RbacManagement.vue'),
    meta: { requiresAuth: true, permission: 'rbac:role:list' }
  },
  {
    path: '/security',
    name: 'SecurityManagement',
    component: () => import('@/views/SecurityManagement.vue'),
    meta: { requiresAuth: true, permission: 'security:component:list' }
  },
  {
    path: '/ssl',
    name: 'SslManagement',
    component: () => import('@/views/SslManagement.vue'),
    meta: { requiresAuth: true, permission: 'ssl:certificate:list' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next('/login')
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/')
  } else {
    next()
  }
})

export default router
