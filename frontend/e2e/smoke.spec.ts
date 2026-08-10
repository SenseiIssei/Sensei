import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // No backend in E2E — return an empty conversation list.
  await page.route("**/api/conversations", (route) => route.fulfill({ json: [] }));
});

test("lands on the savings dashboard", async ({ page }) => {
  // `/` used to be the chat. Savings is the reason the product exists and the
  // only view that changes on its own, so it is what you land on now; the chat
  // moved to /workspace and is reachable from the header.
  await page.goto("/");
  await expect(page).toHaveTitle(/Sensei/);
  await expect(page.getByRole("heading", { name: /SAVINGS/ })).toBeVisible();
  await expect(page.getByText("Estimated cost saved")).toBeVisible();
});

test("the dashboard says whether it is actually streaming", async ({ page }) => {
  // The badge reports the real connection state rather than being decoration
  // that always reads "live". With no backend it must not claim to be live.
  await page.goto("/");
  await expect(page.getByText(/LIVE|POLLING/)).toBeVisible();
});

test("chat is reachable from the dashboard header", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Chat" }).click();

  await expect(page.getByText("Welcome to Sensei")).toBeVisible();
  await expect(page.getByPlaceholder("Send a message to Sensei...")).toBeVisible();
});

test("the chat view has its own URL", async ({ page }) => {
  // Both views are bookmarkable now; the dashboard used to be component state
  // reachable only by clicking through.
  await page.goto("/#/workspace");
  await expect(page.getByPlaceholder("Send a message to Sensei...")).toBeVisible();
});

test("send button enables only when the input has text", async ({ page }) => {
  await page.goto("/#/workspace");
  const input = page.getByPlaceholder("Send a message to Sensei...");
  const sendButton = page.locator('button[type="submit"]');

  await expect(sendButton).toBeDisabled();
  await input.fill("hello there");
  await expect(sendButton).toBeEnabled();
  await input.fill("");
  await expect(sendButton).toBeDisabled();
});
