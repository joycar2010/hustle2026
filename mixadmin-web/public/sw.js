/* Quant Hedge Admin Service Worker (L4)
 * 策略(v2 修订):
 *   - 哈希 /assets 静态资源 = cache-first(命中即用, 内容哈希不可变, 不再后台重复回源)。
 *   - index.html / 导航 = network-first(拿最新构建, 新发布立即生效; 离线才回退缓存壳)。
 *   - /api/**、/ws/**、非 GET、跨域 一律 network-only 不拦(数据永远走网络最新)。
 * 版本号变更即失效旧缓存(activate 清理)。**每次发布若改了缓存语义务必升 VERSION。**
 */
const VERSION = 'mixadmin-v3';
const SHELL = VERSION + '-shell';
// 仅预缓存长期稳定的入口壳(带 hash 的 assets 运行时按需缓存)
const PRECACHE = ['/', '/index.html', '/logo-white.png', '/favicon.ico', '/manifest.webmanifest'];

self.addEventListener('install', (e)=>{
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then(c=>c.addAll(PRECACHE).catch(()=>{})));
});
self.addEventListener('activate', (e)=>{
  e.waitUntil((async()=>{
    const keys = await caches.keys();
    await Promise.all(keys.filter(k=>k!==SHELL).map(k=>caches.delete(k)));  // 清掉 v1 等旧缓存
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', (e)=>{
  const req = e.request;
  let url; try{ url = new URL(req.url); }catch(_){ return; }
  // 命门: 只处理同源 GET; 且【绝不碰】实时 API / WS(数据必须实时最新)
  if(req.method !== 'GET') return;                 // 写操作不拦
  if(url.origin !== self.location.origin) return;  // 跨域(如 qrserver)不拦
  if(url.pathname.startsWith('/api/')) return;      // 后端接口 network-only(绕开)
  if(url.pathname.startsWith('/ws')) return;        // WS 绕开

  const isNav = req.mode === 'navigate' || url.pathname==='/' || url.pathname==='/index.html';
  const isHashedAsset = url.pathname.startsWith('/assets/');   // Vite 内容哈希文件名 → 不可变
  const isStaticShell = /\.(png|jpg|svg|ico|woff2?|webmanifest)$/.test(url.pathname);

  // ① 导航/index.html: network-first(取最新, 新发布立即生效), 离线回退缓存壳
  if(isNav){
    e.respondWith((async()=>{
      const cache = await caches.open(SHELL);
      try{
        const res = await fetch(req);
        if(res && res.status===200){ cache.put('/index.html', res.clone()).catch(()=>{}); }
        return res;
      }catch(_){ return (await cache.match('/index.html')) || (await cache.match('/')) || Response.error(); }
    })());
    return;
  }
  // ② 哈希资源: cache-first, 命中即返(不再后台回源); 未命中→拉一次并缓存
  if(isHashedAsset || isStaticShell){
    e.respondWith((async()=>{
      const cache = await caches.open(SHELL);
      const cached = await cache.match(req);
      if(cached) return cached;
      try{
        const res = await fetch(req);
        if(res && res.status===200 && res.type==='basic'){ cache.put(req, res.clone()).catch(()=>{}); }
        return res;
      }catch(_){ return cached || Response.error(); }
    })());
    return;
  }
  // 其它一律不拦
});
