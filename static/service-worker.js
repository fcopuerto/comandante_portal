'use strict';

const CACHE = 'cobaltax-v3';

// Pre-cache on install — app shell
const PRECACHE_URLS = [
  '/',
  '/static/app.js',
  '/static/style.css',
  '/static/manifest.json',
  '/static/icon.svg',
];

// API paths cached with Network-First strategy (fallback to cache when offline)
const API_PREFIXES = [
  '/api/config',
  '/api/servers',
  '/api/printers',
  '/api/modules',
  '/api/translations/',
  '/api/wiki/',
  '/api/settings',
];

// Never cache these — streaming / mutating endpoints
const NEVER_CACHE = [
  '/api/servers/stream',   // SSE
  '/ws/',                  // WebSocket
  '/api/auth/',
  '/api/printers/ping',
];

// ---- Install: pre-cache app shell ----
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// ---- Activate: remove old caches ----
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ---- Fetch ----
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only intercept same-origin GET requests
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Never cache certain paths
  if (NEVER_CACHE.some(p => url.pathname.startsWith(p))) return;

  const isAPI = API_PREFIXES.some(p => url.pathname.startsWith(p));

  if (isAPI) {
    event.respondWith(_networkFirst(request));
  } else {
    event.respondWith(_cacheFirst(request));
  }
});

// Network first — try live, fall back to cache
async function _networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request.clone());
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) {
      // Tell the page we served a cached response
      _notifyClients({ type: 'offline_cache_hit', url: request.url });
      return cached;
    }
    return new Response(JSON.stringify({ offline: true, error: 'Offline and no cache' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } });
  }
}

// Cache first — serve cached, update in background
async function _cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) {
    fetch(request.clone()).then(r => { if (r.ok) cache.put(request, r); }).catch(() => {});
    return cached;
  }
  try {
    const response = await fetch(request.clone());
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}

// Broadcast a message to all open tabs
function _notifyClients(data) {
  self.clients.matchAll({ includeUncontrolled: true }).then(clients => {
    clients.forEach(c => c.postMessage(data));
  });
}
