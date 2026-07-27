#!/usr/bin/env node
/**
 * Fail the build if the web UI loads anything from a third party.
 *
 * Sensei promises two things that a single stray `<link href="https://fonts…">`
 * quietly breaks: that nothing about you leaves your machine, and that the UI
 * works offline. The Google Fonts tag that used to be in index.html did both.
 *
 * This looks for *resources the page actually fetches* — link/script/img/iframe
 * targets, CSS `url()` and `@import` — not for the string "https://" anywhere in
 * a bundle. Library code is full of documentation links in error messages; a
 * check that flags those gets switched off within a week, which is worse than
 * having no check.
 *
 *   node scripts/check-no-external-assets.mjs [dist-dir]
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const DIST = process.argv[2] ?? "dist";

// Origins a self-hosted page may legitimately point at.
const ALLOWED_HOSTS = [/^localhost$/, /^127\.0\.0\.1$/, /^\[::1\]$/];
// XML namespaces are identifiers, not fetches.
const NAMESPACE_PREFIXES = ["http://www.w3.org/", "http://schema.org/", "https://schema.org/"];

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

function isExternal(url) {
  if (NAMESPACE_PREFIXES.some((p) => url.startsWith(p))) return false;
  if (url.startsWith("data:") || url.startsWith("blob:") || url.startsWith("#")) return false;
  let parsed;
  try {
    parsed = new URL(url, "http://localhost/");
  } catch {
    return false;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
  return !ALLOWED_HOSTS.some((re) => re.test(parsed.hostname));
}

const findings = [];

for (const file of walk(DIST)) {
  const ext = extname(file);
  if (![".html", ".css"].includes(ext)) continue;
  const text = readFileSync(file, "utf8");

  if (ext === ".html") {
    // Any element that causes a fetch: link, script, img, iframe, source, video…
    const tagRe = /<(link|script|img|iframe|source|video|audio|embed|object)\b[^>]*>/gi;
    for (const [tag] of text.matchAll(tagRe)) {
      for (const attr of ["href", "src", "data"]) {
        const m = tag.match(new RegExp(`${attr}\\s*=\\s*["']([^"']+)["']`, "i"));
        if (m && isExternal(m[1])) {
          findings.push({ file, url: m[1], why: `<${tag.match(/<(\w+)/)[1]} ${attr}>` });
        }
      }
    }
    // Preconnect/dns-prefetch to a third party leaks an IP even without a fetch.
    for (const [, rel, href] of text.matchAll(
      /<link\b[^>]*rel\s*=\s*["'](preconnect|dns-prefetch|preload|prefetch)["'][^>]*href\s*=\s*["']([^"']+)["']/gi,
    )) {
      if (isExternal(href)) findings.push({ file, url: href, why: `<link rel="${rel}">` });
    }
  }

  if (ext === ".css") {
    for (const [, url] of text.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/gi)) {
      if (isExternal(url)) findings.push({ file, url, why: "css url()" });
    }
    for (const [, url] of text.matchAll(/@import\s+(?:url\()?\s*["']([^"']+)["']/gi)) {
      if (isExternal(url)) findings.push({ file, url, why: "css @import" });
    }
  }
}

if (findings.length) {
  console.error("The built web UI would fetch from a third party:\n");
  for (const f of findings) {
    console.error(`  ${f.why}  ${f.url}`);
    console.error(`      in ${f.file}`);
  }
  console.error(
    "\nSensei must work offline and must not tell anyone that you opened it.\n" +
      "Vendor the asset into frontend/public/ instead of linking it.",
  );
  process.exit(1);
}

console.log("No third-party resources in the built web UI.");
