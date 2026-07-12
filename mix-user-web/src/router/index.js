import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('@/views/Login.vue'), meta: { requiresAuth: false } },
  { path: '/',       name: 'MixOverview', component: () => import('@/views/MixOverview.vue'), meta: { requiresAuth: true } },
  { path: '/overview-classic', name: 'Overview', component: () => import('@/views/Overview.vue'), meta: { requiresAuth: true } },
  { path: '/fund-flow', name: 'FundFlow', component: () => import('@/views/FundFlow.vue'), meta: { requiresAuth: true } },
  { path: '/manual-ledger', name: 'ManualLedger', component: () => import('@/views/ManualLedger.vue'), meta: { requiresAuth: true } },
  // 20260620: 日/周/月三页已合并进单页收益总览(/), 旧路径重定向到 / 避免书签404
  { path: '/daily',   redirect: '/' },
  { path: '/weekly',  redirect: '/' },
  { path: '/monthly', redirect: '/' },
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
