import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // No backend in E2E — return an empty conversation list.
  await page.route("**/api/conversations", (route) => route.fulfill({ json: [] }));
});

test("renders the app shell and welcome screen", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Sensei/);
  await expect(page.getByText("Welcome to Sensei")).toBeVisible();
  await expect(page.getByText("14+ Providers", { exact: true })).toBeVisible();
  await expect(page.getByPlaceholder("Send a message to Sensei...")).toBeVisible();
});

test("send button enables only when the input has text", async ({ page }) => {
  await page.goto("/");
  const input = page.getByPlaceholder("Send a message to Sensei...");
  const sendButton = page.locator('button[type="submit"]');

  await expect(sendButton).toBeDisabled();
  await input.fill("hello there");
  await expect(sendButton).toBeEnabled();
  await input.fill("");
  await expect(sendButton).toBeDisabled();
});
