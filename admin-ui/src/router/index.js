import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../store/auth'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue') },
  {
    path: '/', component: () => import('../layout/Layout.vue'),
    children: [
      { path: '', redirect: '/overview' },
      { path: 'overview', component: () => import('../views/Overview.vue'), meta: { title: '总览' } },
      { path: 'engine', component: () => import('../views/EngineCtl.vue'), meta: { title: '引擎控制' } },
      { path: 'routes', component: () => import('../views/Routes.vue'), meta: { title: '路由' } },
      { path: 'alerts', component: () => import('../views/Alerts.vue'), meta: { title: '告警历史' } },
      { path: 'audit', component: () => import('../views/Audit.vue'), meta: { title: '操作审计' } },
      { path: 'lending', component: () => import('../views/Lending.vue'), meta: { title: '借贷增强' } },
      { path: 'pnl', component: () => import('../views/Pnl.vue'), meta: { title: 'PnL 归因' } },
      { path: 'coin', component: () => import('../views/CoinBridge.vue'), meta: { title: 'coin 借币' } },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach((to) => {
  const auth = useAuth()
  if (to.path !== '/login' && !auth.authed) return '/login'
  if (to.path === '/login' && auth.authed) return '/overview'
})
export default router
