/* Quant Hedge Service Worker — 离线壳缓存
   铁律: 严格绕开一切实时接口 —— /api(REST) 与 /ws(WebSocket) 一律不拦、不缓存,直连网络。
   只缓存静态外壳(HTML/图标/manifest),保证离线能打开壳,实时数据永远走网络最新。 */
const CACHE = 'qh-shell-v2';
const SHELL = [
  '/', '/dashboard',
  '/index.html',
  '/manifest.json',
  '/QHEDGELOGO-512.png',
  '/QHEDGELOGO-mid.png',
  '/QHEDGELOGO-s-single.ico'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  // 只处理 GET; 非 GET(POST 下单/授权等)直接放行
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // ===== 铁律: 实时接口一律不碰 =====
  // /api 任意路径(REST) + /ws 任意路径(WebSocket 握手也是 GET) → 直连网络, SW 不介入
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')) return;

  // 跨域(交易所/第三方)不缓存
  if (url.origin !== self.location.origin) return;

  // 导航请求(打开页面): 网络优先, 失败回退缓存壳(离线也能开)
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).catch(() => caches.match('/index.html').then((r) => r || caches.match('/')))
    );
    return;
  }

  // 静态资源(js/css/图标/字体): 缓存优先, 后台更新(stale-while-revalidate)
  e.respondWith(
    caches.match(req).then((cached) => {
      const net = fetch(req).then((resp) => {
        if (resp && resp.status === 200 && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return resp;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
