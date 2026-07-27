/**
 * Register the service worker, in production only.
 *
 * In dev it would serve stale modules and make HMR behave inexplicably, which
 * costs more time than the offline support is worth while developing.
 */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return;
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", () => {
    // `updateViaCache: "none"` is load-bearing. Without it the browser may
    // serve sw.js from its own HTTP cache, so a redeploy keeps running the old
    // worker — including its old precache list, which then points at asset
    // filenames that no longer exist. This was not theoretical: it silently
    // left the cache empty during testing.
    //
    // The path is relative to the page so it works both at `/` (vite preview)
    // and at `/app/` (where the backend mounts the built UI).
    navigator.serviceWorker.register("./sw.js", { updateViaCache: "none" }).then(
      (reg) => {
        // A new build is available: activate it rather than leaving the user
        // on an old bundle until every tab is closed.
        reg.addEventListener("updatefound", () => {
          const installing = reg.installing;
          if (!installing) return;
          installing.addEventListener("statechange", () => {
            if (installing.state === "installed" && navigator.serviceWorker.controller) {
              installing.postMessage("skip-waiting");
            }
          });
        });
      },
      () => {
        // Registration failing is not worth bothering the user about — the app
        // works, it just won't be available offline.
      },
    );
  });
}
