import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: () => import('./views/Login.vue') },
  { path: '/dashboard', name: 'dashboard', component: () => import('./views/Dashboard.vue'), meta: { auth: true } },
  { path: '/decisions', name: 'decisions', component: () => import('./views/Decisions.vue'), meta: { auth: true } },
  { path: '/proposals', name: 'proposals', component: () => import('./views/Proposals.vue'), meta: { auth: true } },
  { path: '/risk', name: 'risk', component: () => import('./views/RiskControl.vue'), meta: { auth: true } },
  { path: '/infra', name: 'infra', component: () => import('./views/Infrastructure.vue'), meta: { auth: true } },
  { path: '/ladder-advisor', name: 'ladderAdvisor', component: () => import('./views/LadderAdvisor.vue'), meta: { auth: true } },
  { path: '/settings', redirect: '/risk' },
]

const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.auth && !token) return next('/login')
  next()
})
export default router
