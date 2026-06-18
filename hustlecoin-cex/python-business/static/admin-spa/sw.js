/* CoinAdmin Service Worker — 离线壳 + 不可变资源缓存(scope: /admin/)
 * 安全边界:绝不缓存/拦截 /api、/ws —— 管理数据必须始终直连网络。
 * 策略:导航 network-first;/admin/assets 带 hash 资源 cache-first;其它直连。
 */
const CACHE = 'coinadmin-shell-v1'
const SHELL = ['/admin/', '/admin/index.html']

self.addEventListener('install', (e) => {
  self.skipWaiting()
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  let url
  try { url = new URL(req.url) } catch { return }
  if (url.origin !== self.location.origin) return
  // 实时/管理数据通道绝不拦截
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws') || url.pathname.includes('/stream')) return

  // 导航 HTML:network-first,断网回退缓存壳
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put('/admin/index.html', copy)).catch(() => {})
          return res
        })
        .catch(() => caches.match(req).then((m) => m || caches.match('/admin/index.html')).then((m) => m || caches.match('/admin/')))
    )
    return
  }

  // 静态不可变资源:cache-first + 后台回填
  if (url.pathname.startsWith('/admin/assets/') || /\.(?:js|css|woff2?|ttf|png|svg|jpe?g|webp|ico|gif)$/.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {})
        }
        return res
      }).catch(() => cached))
    )
    return
  }
  // 其它:默认直连网络
})
