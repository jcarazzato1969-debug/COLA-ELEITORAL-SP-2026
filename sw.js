// Remove o service worker antigo do Álbum da Copa, que ficava na raiz do site.
// O álbum agora está em ./album-copa/ (com o próprio service worker) e a raiz é a Cola Eleitoral.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    await self.clients.claim();
    await caches.delete('album2026-v1');
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(c => c.navigate(c.url));
  })());
});
