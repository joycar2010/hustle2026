import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('@/views/Login.vue'), meta: { requiresAuth: false } },
  { path: '/',       name: 'Overview', component: () => import('@/views/Overview.vue'), meta: { requiresAuth: true } },
  { path: '/daily',  name: 'Daily',    component: () => import('@/views/Daily.vue'),    meta: { requiresAuth: true } },
  { path: '/weekly', name: 'Weekly',   component: () => import('@/views/Weekly.vue'),   meta: { requiresAuth: true } },
  { path: '/monthly',name: 'Monthly',  component: () => import('@/views/Monthly.vue'),  meta: { requiresAuth: true } },
  { path: '/fund-flow', name: 'FundFlow', component: () => import('@/views/FundFlow.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth === false) {
    if (auth.isAuthenticated) return next('/')
    return next()
  }
  if (!auth.isAuthenticated) return next('/login')
  // Sub-account cannot visit fund-flow
  if (to.path === '/fund-flow' && auth.viewCaps && auth.viewCaps.fund_flow === false) {
    return next('/')
  }
  next()
})

export default router
