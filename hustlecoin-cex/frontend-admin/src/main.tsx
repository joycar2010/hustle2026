import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// [第三梯队] 注册 Service Worker(scope /admin/):离线壳 + 弱网秒开。sw.js 绝不缓存 /api、/ws。
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // 域名隔离保险:注销本域名上 scope=/ 的流氓 SW(历史上用户端壳曾在 coinadmin 域名的非
    // /admin 路径加载并注册 /sw.js scope=/,劫持全站导航吐 coin dashboard 缓存壳)。
    // nginx 已把非 /admin 路径 302 + /sw.js 404(更新检查 404 会自动注销),这里是双保险加速恢复。
    navigator.serviceWorker.getRegistrations?.().then((regs) => {
      for (const r of regs) {
        try {
          if (new URL(r.scope).pathname === '/') r.unregister()
        } catch { /* ignore */ }
      }
    }).catch(() => {})
    navigator.serviceWorker.register('/admin/sw.js', { scope: '/admin/' }).catch(() => {})
  })
}
