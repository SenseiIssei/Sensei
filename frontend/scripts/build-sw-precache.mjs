#!/usr/bin/env node
/**
 * Inject the built asset list into the service worker's precache.
 *
 * Without this the service worker caches index.html but none of the hashed
 * JS/CSS, because those are only cached on a *subsequent* fetch — and on a
 * first visit the browser has already requested them before the worker takes
 * control. The result is the worst possible failure mode: offline, the shell
 * loads and the app never boots, so Sensei looks broken rather than offline.
 *
 * Enumerating dist/assets after the build is complete by construction — it
 * cannot miss a lazily-imported chunk the way parsing index.html would.
 *
 *   node scripts/build-sw-precache.mjs [dist-dir]
 */

import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const DIST = process.argv[2] ?? "dist";
const SW = join(DIST, "sw.js");
const MARKER = "/* __PRECACHE_ASSETS__ */";

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const assetDir = join(DIST, "assets");
let assets = [];
try {
  assets = walk(assetDir)
    .map((f) => "./" + relative(DIST, f).split(sep).join("/"))
    .sort();
} catch {
  console.error(`No ${assetDir} directory — did the build run?`);
  process.exit(1);
}

const source = readFileSync(SW, "utf8");
if (!source.includes(MARKER)) {
  console.error(`${SW} is missing the ${MARKER} marker; cannot inject the precache list.`);
  process.exit(1);
}

const injected = source.replace(
  MARKER,
  `// Generated at build time by scripts/build-sw-precache.mjs.\n` +
    `const BUILD_ASSETS = ${JSON.stringify(assets, null, 2)};`,
);

writeFileSync(SW, injected, "utf8");
console.log(`Precached ${assets.length} built asset(s) into ${SW}.`);
