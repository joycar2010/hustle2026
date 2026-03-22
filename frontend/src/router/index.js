import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const ADMIN_URL = 'https://admin.hustle2026.xyz'

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
    path: '/risk',
    name: 'Risk',
    component: () => import('@/views/Risk.vue'),
    meta: { requiresAuth: true }
  },
  // 以下路由已迁移至 admin.hustle2026.xyz，访问时直接跳转
  {
    path: '/strategies',
    beforeEnter: () => { window.location.href = ADMIN_URL + '/strategies' }
  },
  {
    path: '/positions',
    beforeEnter: () => { window.location.href = ADMIN_URL + '/spread' }
  },
  {
    path: '/accounts',
    beforeEnter: () => { window.location.href = ADMIN_URL + '/users' }
  },
  {
    path: '/system',
    beforeEnter: () => { window.location.href = ADMIN_URL + '/system' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth === false) {
    next()
  } else if (!authStore.isAuthenticated) {
    next('/login')
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    next('/')
  } else {
    next()
  }
})

export default router
