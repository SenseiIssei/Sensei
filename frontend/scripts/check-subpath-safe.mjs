#!/usr/bin/env node
/**
 * The built UI must work when it is not served from the web root.
 *
 * `sensei up`, the packaged binaries and the launcher all mount the UI at
 * `/app/`. If Vite emits root-absolute asset URLs (`/assets/…`) those requests
 * miss the mount and hit the API, which answers 404 with JSON — and a browser
 * that is handed JSON for a module script simply does nothing. The result is a
 * blank page with an empty console, from a build that looks perfectly fine.
 *
 * That is exactly what shipped until `base: "./"` was set, so this asserts the
 * invariant rather than trusting the config to stay put.
 *
 *   node scripts/check-subpath-safe.mjs [dist-dir]
 */

import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const DIST = process.argv[2] ?? "dist";
const INDEX = join(DIST, "index.html");

if (!existsSync(INDEX)) {
  console.error(`No ${INDEX} — did the build run?`);
  process.exit(1);
}

const html = readFileSync(INDEX, "utf8");
const bad = [];

for (const [, attr, url] of html.matchAll(/\b(src|href)\s*=\s*["'](\/[^"'/][^"']*)["']/g)) {
  bad.push(`${attr}="${url}"`);
}

if (bad.length) {
  console.error("index.html contains root-absolute references:\n");
  for (const b of bad) console.error(`  ${b}`);
  console.error(
    "\nThese 404 when the UI is mounted under a sub-path such as /app/,\n" +
      'and the page renders blank with no error. Keep `base: "./"` in vite.config.ts.',
  );
  process.exit(1);
}

console.log("index.html uses relative references — safe to mount under a sub-path.");
