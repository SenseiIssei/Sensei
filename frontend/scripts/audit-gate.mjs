#!/usr/bin/env node
/**
 * npm audit as a CI gate, with reviewed exceptions.
 *
 *   node scripts/audit-gate.mjs [--level=high] [--allowlist=audit-allowlist.json]
 *
 * Exits non-zero when an advisory at or above `level` is not in the allowlist,
 * or when an allowlist entry has passed its review_by date. Zero dependencies —
 * it shells out to `npm audit --json` and reads the result.
 */

import { execSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, v] = a.replace(/^--/, "").split("=");
    return [k, v ?? true];
  }),
);

const LEVEL = args.level ?? "high";
const ALLOWLIST_PATH = args.allowlist ?? "audit-allowlist.json";
const RANK = { info: 0, low: 1, moderate: 2, high: 3, critical: 4 };
const threshold = RANK[LEVEL];

if (threshold === undefined) {
  console.error(`Unknown level "${LEVEL}". Use one of: ${Object.keys(RANK).join(", ")}`);
  process.exit(2);
}

function runAudit() {
  try {
    // Constant command, so the shell is safe here — and necessary, because npm
    // is a .cmd shim on Windows that execFile refuses to spawn directly.
    // npm audit exits non-zero whenever it finds anything, so the throw below
    // is the normal path, not the error path.
    return JSON.parse(
      execSync("npm audit --json", { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 }),
    );
  } catch (err) {
    if (err.stdout) return JSON.parse(err.stdout);
    console.error("Could not run `npm audit`:", err.message);
    process.exit(2);
  }
}

function loadAllowlist() {
  if (!existsSync(ALLOWLIST_PATH)) return [];
  const parsed = JSON.parse(readFileSync(ALLOWLIST_PATH, "utf8"));
  return parsed.allow ?? [];
}

/** Every advisory id attached to a vulnerability, at or above the threshold. */
function findings(report) {
  const out = [];
  for (const [name, vuln] of Object.entries(report.vulnerabilities ?? {})) {
    if ((RANK[vuln.severity] ?? 0) < threshold) continue;
    for (const via of vuln.via ?? []) {
      if (typeof via === "string") continue; // transitive pointer, not an advisory
      const id = via.url?.split("/").pop();
      if (id) out.push({ id, package: via.name ?? name, severity: via.severity, title: via.title });
    }
  }
  // The same advisory shows up once per affected package path.
  return [...new Map(out.map((f) => [f.id + f.package, f])).values()];
}

const allowlist = loadAllowlist();
const today = new Date().toISOString().slice(0, 10);

const expired = allowlist.filter((e) => e.review_by && e.review_by < today);
const allowed = new Set(allowlist.filter((e) => !expired.includes(e)).map((e) => e.id));

const found = findings(runAudit());
const blocking = found.filter((f) => !allowed.has(f.id));
const waived = found.filter((f) => allowed.has(f.id));

for (const w of waived) {
  const entry = allowlist.find((e) => e.id === w.id);
  console.log(`waived  ${w.severity.padEnd(8)} ${w.id}  ${w.package}`);
  console.log(`        reviewed until ${entry.review_by}: ${entry.reason.split(".")[0]}.`);
}

for (const e of expired) {
  console.error(`::error::Allowlist entry ${e.id} expired on ${e.review_by}. Re-assess it and`);
  console.error(`         either extend review_by with fresh reasoning, or fix the dependency.`);
}

for (const f of blocking) {
  console.error(`::error::${f.severity} ${f.id} in ${f.package}: ${f.title}`);
  console.error(`         https://github.com/advisories/${f.id}`);
}

if (blocking.length || expired.length) {
  console.error(
    `\n${blocking.length} unreviewed advisory/advisories at ${LEVEL}+, ` +
      `${expired.length} expired waiver(s).`,
  );
  process.exit(1);
}

console.log(`\nNo unreviewed advisories at ${LEVEL} or above.`);
