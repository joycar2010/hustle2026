import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('@/views/Login.vue'), meta: { requiresAuth: false } },
  { path: '/',      name: 'Overview', component: () => import('@/views/Overview.vue'), meta: { requiresAuth: true } },
  { path: '/history', name: 'History', component: () => import('@/views/History.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth === false) {
    if (auth.isAuthenticated) return next('/')
    return next()
  }
  if (!auth.isAuthenticated) return next('/login')
  next()
})

export default router
