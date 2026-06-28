import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/conversations", (route) => route.fulfill({ json: [] }));
});

test("streams an assistant reply over a mocked chat WebSocket", async ({ page }) => {
  // Mock the chat WebSocket: reply to the client's message with meta + tokens + done.
  await page.routeWebSocket(/\/api\/chat\/ws/, (ws) => {
    ws.onMessage(() => {
      ws.send(
        JSON.stringify({
          type: "meta",
          conversation_id: "conv-e2e",
          tokens_saved: 42,
          compression_enabled: true,
          model: "test-model",
        })
      );
      ws.send(JSON.stringify({ type: "token", content: "Hello " }));
      ws.send(JSON.stringify({ type: "token", content: "world" }));
      ws.send(JSON.stringify({ type: "done" }));
    });
  });

  await page.goto("/");
  const input = page.getByPlaceholder("Send a message to Sensei...");
  await input.fill("hi");
  await input.press("Enter");

  await expect(page.getByText("Hello world")).toBeVisible();
  await expect(page.getByText("42 tokens saved")).toBeVisible();
});
