/*
 * Service worker for the Sensei web UI.
 *
 * Deliberately hand-written and dependency-free: Workbox would add a build
 * step and ~20 kB to cache seven files, and a self-hosted tool should be able
 * to explain every byte it ships.
 *
 * Two rules, and the second one is the important one:
 *
 *   1. The app shell is cached, so opening Sensei is instant and works when
 *      the backend is down — you get the interface telling you the backend is
 *      down, rather than a blank page with a browser error.
 *
 *   2. `/api/**` is NEVER cached. Not stale-while-revalidate, not
 *      network-first-with-fallback — never. A cached conversation, a cached
 *      model list, or worst of all a cached settings response would show you
 *      state that isn't real, in a tool whose whole job is handling your
 *      private data correctly. Wrong data is worse than no data here.
 */

const VERSION = "v1";
const SHELL_CACHE = `sensei-shell-${VERSION}`;
const ASSET_CACHE = `sensei-assets-${VERSION}`;

const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./sensei.svg"];

/* __PRECACHE_ASSETS__ */

// The hashed JS/CSS must be precached at install, not lazily on a later fetch.
// On a first visit the browser requests them before this worker takes control,
// so a lazy strategy leaves them uncached — and offline you get the shell with
// no app in it, which looks like Sensei is broken rather than offline.
const PRECACHE = SHELL.concat(typeof BUILD_ASSETS !== "undefined" ? BUILD_ASSETS : []);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // allSettled rather than addAll: addAll is atomic, so a single 404 on a
      // partial deploy would leave no cache at all — a worse outcome than an
      // incomplete one.
      .then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("sensei-") && k !== SHELL_CACHE && k !== ASSET_CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});

function isApiRequest(url) {
  return (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/v1/") ||
    url.pathname === "/health"
  );
}

/** Hashed build output: content-addressed, so caching forever is safe. */
function isImmutableAsset(url) {
  return /\/assets\/.+-[A-Za-z0-9_-]{8,}\.(js|css|woff2?|png|svg|jpg|webp)$/.test(url.pathname);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Only handle our own origin. Nothing else should exist, but a service
  // worker silently proxying third-party requests would be exactly the kind
  // of thing this project promises not to do.
  if (url.origin !== self.location.origin) return;

  if (isApiRequest(url)) return; // straight to the network, always

  if (isImmutableAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ??
          fetch(request).then((resp) => {
            if (resp.ok) {
              const copy = resp.clone();
              caches.open(ASSET_CACHE).then((c) => c.put(request, copy));
            }
            return resp;
          }),
      ),
    );
    return;
  }

  // Navigations and everything else: try the network so a redeploy is picked
  // up immediately, fall back to the cached shell when offline.
  event.respondWith(
    fetch(request)
      .then((resp) => {
        if (resp.ok && request.mode === "navigate") {
          const copy = resp.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(request, copy));
        }
        return resp;
      })
      .catch(async () => {
        const cached = await caches.match(request);
        if (cached) return cached;
        const shell = await caches.match("./index.html");
        if (shell) return shell;
        return new Response("Sensei is offline and nothing is cached yet.", {
          status: 503,
          headers: { "Content-Type": "text/plain" },
        });
      }),
  );
});
