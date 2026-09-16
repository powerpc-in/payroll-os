// Vetan PWA service worker — pass-through by design.
// The app is API-driven (httpOnly-cookie authenticated), so nothing sensitive is
// cached here. The manifest enables install to Android/iOS home screens and
// Windows desktop; offline resilience is handled in-app with an offline banner
// and react-query's cache of last-good data.
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // network-only passthrough; SW exists so the browser treats the app as installable
});
