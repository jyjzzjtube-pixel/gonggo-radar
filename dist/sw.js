const C='radar-v1';
const ASSETS=['./','./index.html','./manifest.json'];
self.addEventListener('install',e=>{self.skipWaiting();
  e.waitUntil(caches.open(C).then(c=>c.addAll(ASSETS)).catch(()=>{}))});
self.addEventListener('activate',e=>{e.waitUntil(
  caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(u.pathname.endsWith('data.json')){
    // 데이터는 네트워크 우선, 실패 시 캐시(오프라인에서도 마지막 목록 열람)
    e.respondWith(fetch(e.request).then(r=>{
      const cp=r.clone(); caches.open(C).then(c=>c.put(e.request,cp)); return r;
    }).catch(()=>caches.match(e.request)));
  } else {
    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));
  }
});