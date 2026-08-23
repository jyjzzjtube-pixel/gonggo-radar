/* 공공공고 레이더 서비스워커
   HTML/JSON = 네트워크 우선(배포 즉시 반영, 오프라인이면 캐시)
   아이콘 등 정적 자산 = 캐시 우선 */
const C = 'radar-v3';
const PRECACHE = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(C).then(c => c.addAll(PRECACHE)).catch(() => {}));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function networkFirst(req) {
  return fetch(req).then(r => {
    const cp = r.clone();
    caches.open(C).then(c => c.put(req, cp));
    return r;
  }).catch(() => caches.match(req).then(r => r || caches.match('./index.html')));
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;   // 외부 공고 원문은 건드리지 않는다

  const isHTML = req.mode === 'navigate' ||
                 url.pathname.endsWith('/') ||
                 url.pathname.endsWith('.html');
  const isData = url.pathname.endsWith('data.json');

  if (isData) {
    // 데이터는 항상 네트워크. 실패했을 때만 마지막으로 받아둔 캐시를 쓴다.
    e.respondWith(fetch(req).then(r => {
      const cp = r.clone();
      caches.open(C).then(c => c.put('./data.json', cp));
      return r;
    }).catch(() => caches.match('./data.json')));
  } else if (isHTML) {
    e.respondWith(networkFirst(req));
  } else {
    e.respondWith(caches.match(req).then(r => r || fetch(req)));
  }
});
