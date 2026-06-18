/* HustleCoin Service Worker — 离线壳 + 不可变资源缓存
 * 安全边界:绝不缓存/拦截 /api、/ws、/stream —— 实时交易数据必须始终直连网络,杜绝陈旧行情/余额/订单。
 * 策略:
 *   - 导航(HTML):network-first —— 部署后立刻拿到新壳,断网才回退缓存壳;
 *   - /assets 带 hash 的不可变资源:cache-first —— 离线/弱网秒开,新 hash 自然回源缓存;
 *   - 其它:直连网络(默认)。
 */
const CACHE = 'hc-shell-v1'
const SHELL = ['/', '/index.html']

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
  // 实时数据通道绝不拦截 —— 始终走网络
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws') || url.pathname.includes('/stream')) return

  // 导航 HTML:network-first,断网回退缓存壳
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put('/index.html', copy)).catch(() => {})
          return res
        })
        .catch(() => caches.match(req).then((m) => m || caches.match('/index.html')).then((m) => m || caches.match('/')))
    )
    return
  }

  // 静态不可变资源:cache-first + 后台回填
  if (url.pathname.startsWith('/assets/') || /\.(?:js|css|woff2?|ttf|png|svg|jpe?g|webp|ico|gif)$/.test(url.pathname)) {
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
