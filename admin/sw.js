/* Quant Hedge Admin Service Worker (L4)
 * 策略: 静态壳 cache-first(离线可开壳), 但【严格绕开一切实时/写接口】——
 *   /api/**、/ws/**、非 GET 请求 一律 network-only 不缓存(数据永远走网络最新, 绝不返陈旧)。
 * 版本号变更即失效旧缓存(激活时清理)。
 */
const VERSION = 'qhadmin-v1';
const SHELL = VERSION + '-shell';
// 仅预缓存能长期稳定的入口壳(带 hash 的 assets 由运行时按需缓存)
const PRECACHE = ['/', '/index.html', '/logo-white.png', '/favicon.ico', '/manifest.webmanifest'];

self.addEventListener('install', (e)=>{
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then(c=>c.addAll(PRECACHE).catch(()=>{})));
});
self.addEventListener('activate', (e)=>{
  e.waitUntil((async()=>{
    const keys = await caches.keys();
    await Promise.all(keys.filter(k=>k!==SHELL).map(k=>caches.delete(k)));
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
  // 静态资源: cache-first + 后台回填(stale-while-revalidate 简版)
  const isAsset = url.pathname.startsWith('/assets/') || /\.(js|css|png|jpg|svg|ico|woff2?|webmanifest)$/.test(url.pathname);
  const isNav = req.mode === 'navigate';
  if(!isAsset && !isNav) return;                    // 其它一律不拦
  e.respondWith((async()=>{
    const cache = await caches.open(SHELL);
    const cached = await cache.match(req, {ignoreSearch:false});
    const net = fetch(req).then(res=>{
      if(res && res.status===200 && res.type==='basic'){ cache.put(req, res.clone()).catch(()=>{}); }
      return res;
    }).catch(()=> cached || (isNav ? cache.match('/index.html') : undefined));
    // 资源: 有缓存先返(快), 后台更新; 导航: 同理回退 index.html(SPA 离线壳)
    return cached || net;
  })());
});
