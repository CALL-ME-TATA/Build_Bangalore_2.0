// Service worker: caches the app shell only. API calls and the WebSocket are never cached.
// Shell files are fetched network-first so a code change shows up on the next load;
// the cached copy is used only when the network fails.
const CACHE = 'khatavaani-shell-v1';
const SHELL = [
  './', 'index.html', 'styles.css', 'app.js', 'ui.js', 'controller.js', 'store.js', 'ws.js', 'api.js', 'format.js',
  'audio/dsp.js', 'audio/player.js', 'audio/capture-worklet.js', 'vendor/htm-preact.js', 'icon.svg', 'manifest.webmanifest',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
        return res;
      })
      .catch(() => caches.match(e.request)),
  );
});
