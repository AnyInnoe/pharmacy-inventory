const CACHE_PREFIX = 'wellnest-shell-'
const CACHE_NAME = `${CACHE_PREFIX}v1`

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME)
    const response = await fetch('/', { cache: 'reload' })
    if (!response.ok) throw new Error('Could not cache the application shell.')
    const html = await response.clone().text()
    await cache.put('/', response.clone())
    await cache.put('/index.html', response.clone())

    const assets = Array.from(
      html.matchAll(/(?:src|href)=["']([^"']+\.(?:js|css))["']/gi),
      (match) => new URL(match[1], self.location.origin),
    ).filter((url) => url.origin === self.location.origin)
    await Promise.all(assets.map(async (url) => {
      const assetResponse = await fetch(url)
      if (!assetResponse.ok) throw new Error(`Could not cache app asset: ${url.pathname}`)
      await cache.put(url.pathname, assetResponse)
    }))
    await self.skipWaiting()
  })())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys()
    await Promise.all(cacheNames
      .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map((name) => caches.delete(name)))
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(async () => (
      await caches.match('/') || Response.error()
    )))
    return
  }

  if (url.pathname.startsWith('/assets/')) {
    event.respondWith((async () => {
      const cached = await caches.match(request)
      if (cached) return cached
      const response = await fetch(request)
      if (response.ok) {
        const cache = await caches.open(CACHE_NAME)
        await cache.put(request, response.clone())
      }
      return response
    })())
  }
})
