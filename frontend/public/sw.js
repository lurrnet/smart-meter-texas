/* Cache only versioned static Vite assets. Never cache HTML, API or auth responses. */
const CACHE = "smt-static-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("smt-static-") && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || request.mode === "navigate") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !/^\/assets\/[\w.-]+-[A-Za-z0-9_-]{8,}\.(?:js|css)$/.test(url.pathname)) return;
  // No cache access for sensitive endpoints; reject non-asset requests by default.
  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok && response.type === "basic" && !response.redirected &&
        !response.headers.has("set-cookie") &&
        !/(?:no-store|private)/i.test(response.headers.get("cache-control") || "") &&
        /(?:javascript|text\/css)/i.test(response.headers.get("content-type") || "")) {
      const cache = await caches.open(CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  })());
});
