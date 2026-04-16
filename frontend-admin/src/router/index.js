import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const ADMIN_ROLES = ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    name: 'MasterDashboard',
    component: () => import('@/views/MasterDashboard.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/ws-monitor',
    name: 'WsMonitor',
    component: () => import('@/views/WsMonitor.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/spread',
    name: 'SpreadAnalysis',
    component: () => import('@/views/SpreadAnalysis.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/strategies',
    name: 'Strategies',
    component: () => import('@/views/Strategies.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/hedging',
    name: 'HedgingManagement',
    component: () => import('@/views/HedgingManagement.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/users',
    name: 'UserManagement',
    component: () => import('@/views/UserManagement.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/system',
    name: 'SystemAdmin',
    component: () => import('@/views/SystemAdmin.vue'),
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth === false) {
    if (authStore.isAuthenticated) return next('/')
    return next()
  }

  if (!authStore.isAuthenticated) return next('/login')

  // 确保用户信息和角色已加载
  if (!authStore.user || !authStore.userRole) {
    await authStore.fetchUser()
  }

  const hasAdminRole = ADMIN_ROLES.includes(authStore.userRole)
  if (!hasAdminRole) {
    authStore.logout()
    return next('/login?error=permission')
  }

  next()
})

export default router
