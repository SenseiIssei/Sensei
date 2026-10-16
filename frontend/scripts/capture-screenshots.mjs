#!/usr/bin/env node
/**
 * README screenshots, reproducibly.
 *
 *   node scripts/capture-screenshots.mjs [http://localhost:7000/app/] [../docs/screenshots]
 *
 * Point it at a running Sensei that has seen some traffic. Every view is
 * captured in dark and light at 2x, plus the phone layout. Nothing is mocked:
 * what the page shows is what the server returned.
 */

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";

const base = (process.argv[2] ?? "http://localhost:7000/app/").replace(/\/?$/, "/");
const out = resolve(process.argv[3] ?? "../docs/screenshots");
mkdirSync(out, { recursive: true });

const views = [
  { name: "overview", hash: "#/" },
  { name: "connections", hash: "#/connections" },
  { name: "settings", hash: "#/settings" },
  { name: "chat", hash: "#/workspace" },
];

// CHROMIUM_PATH lets an older, already-installed Chromium do the job.
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
try {
  for (const theme of ["dark", "light"]) {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: theme,
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    for (const view of views) {
      await page.goto(base + view.hash);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      // Settings waits on hardware detection, which takes a few seconds.
      await page.waitForTimeout(view.name === "settings" ? 4000 : 1000);
      const file = `${out}/${view.name}-${theme}.png`;
      await page.screenshot({ path: file });
      console.log("wrote", file);
    }
    await context.close();
  }

  const phone = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    colorScheme: "dark",
    reducedMotion: "reduce",
    isMobile: true,
    hasTouch: true,
  });
  const page = await phone.newPage();
  await page.goto(base);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/mobile-dark.png` });
  console.log("wrote", `${out}/mobile-dark.png`);
  await phone.close();
} finally {
  await browser.close();
}
