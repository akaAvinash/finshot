import { expect, test } from "@playwright/test";
import { signInStaging } from "./staging-helpers";

const fixture = "http://127.0.0.1:3102/__fixture";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
  expect((await request.post(`${fixture}/workspace/enable`)).status()).toBe(204);
});

test("persists broker actions and shows the server rejection in the confirmation dialog", async ({ page, request }) => {
  await signInStaging(page);
  await page.goto("/brokers");
  const broker = page.getByRole("region", { name: "Zerodha" });
  await broker.getByRole("button", { name: "Connect demo" }).click();
  const dialog = page.getByRole("dialog", { name: "Connect Zerodha demo?" });
  await request.post(`${fixture}/workspace/reject-broker`);
  await dialog.getByRole("button", { name: "Connect demo account" }).click();
  await expect(dialog.getByRole("alert")).toContainText("The broker connection changed.");
  await dialog.getByRole("button", { name: "Connect demo account" }).click();
  await expect(broker.getByText("•••• 0248")).toBeVisible();

  await page.reload();
  await expect(broker.getByText("•••• 0248")).toBeVisible();
  await broker.getByRole("button", { name: "Sync demo account" }).click();
  await expect(page.getByText("Zerodha demo account synced")).toBeVisible();
  await broker.getByRole("button", { name: "Disconnect" }).click();
  await page.getByRole("button", { name: "Disconnect demo account" }).click();
  await expect(broker.getByRole("button", { name: "Connect demo" })).toBeVisible();
  await page.reload();
  await expect(broker.getByRole("button", { name: "Connect demo" })).toBeVisible();
  await expect(page.getByLabel("Broker preview data")).toHaveCount(0);
});

test("recovers a pending backtest after reload and runs an approved strategy to a paper fill", async ({ page }) => {
  await signInStaging(page);
  await page.goto("/strategies");
  await page.getByRole("button", { name: "Create strategy" }).click();
  await page.getByLabel("Strategy name").fill("Staging NIFTY demo");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("button", { name: "View Staging NIFTY demo" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "View Staging NIFTY demo" }).click();
  await expect(page.getByRole("button", { name: "Activate demo" })).toBeDisabled();
  await page.getByRole("button", { name: "Edit draft" }).click();
  await page.getByLabel("Strategy name").fill("Staging NIFTY revised");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("dialog", { name: "Staging NIFTY revised" })).toBeVisible();
  await page.getByRole("link", { name: "Open Backtesting" }).click();
  await expect(page.getByLabel("Strategy revision").locator("option:checked")).toContainText("Staging NIFTY revised · Draft");
  await page.getByRole("button", { name: "Run demo backtest" }).click();
  await expect(page.getByRole("region", { name: "Run queue" })).toContainText("Queued");
  await page.reload();
  await expect(page.getByRole("region", { name: "Run queue" })).toContainText("Completed", { timeout: 12_000 });

  await page.goto("/strategies");
  await page.getByRole("button", { name: "View Staging NIFTY revised" }).click();
  await page.getByRole("button", { name: "Activate demo" }).click();
  await expect(page.getByText("Version 1", { exact: false })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "View Staging NIFTY revised" }).click();
  await expect(page.getByRole("button", { name: "Pause demo" })).toBeEnabled();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/auto-trading");
  await page.getByLabel("Assigned strategy").selectOption({ label: "Staging NIFTY revised · NIFTY 50" });
  await page.getByRole("button", { name: "Start paper engine" }).click();
  await expect(page.getByRole("button", { name: "Pause paper engine" })).toBeVisible();
  await page.getByRole("tab", { name: "Trade log" }).click();
  await expect(page.getByRole("rowheader", { name: "NIFTY 50" })).toBeVisible({ timeout: 12_000 });

  const limits = page.getByRole("region", { name: "Trade Controls" });
  await expect(limits).toContainText("₹1,800");
  await expect(limits).toContainText("1 / 8");
  await expect(limits).toContainText("unavailable in staging");
  await expect(limits.getByRole("button")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.getByRole("button", { name: "Pause paper engine" }).click();
  await expect(page.getByRole("button", { name: "Start paper engine" })).toBeEnabled();
  await page.getByRole("button", { name: "Paper kill switch" }).click();
  await page.getByLabel("Type STOP to confirm").fill("STOP");
  await page.getByRole("button", { name: "Confirm paper halt" }).click();
  await expect(page.getByRole("button", { name: "Clear paper halt" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Clear paper halt" })).toBeVisible();
  await page.getByRole("tab", { name: "Trade log" }).click();
  await expect(page.getByRole("rowheader", { name: "NIFTY 50" })).toBeVisible();
});

test("shows read-only agent health and pages server events without enabling commands", async ({ page, context, request }) => {
  for (const path of ["backtests/preview", "agents", "agents/health", "agents/events"]) {
    expect((await request.get(`/api/v1/${path}`)).status()).toBe(401);
  }
  await signInStaging(page);
  await page.goto("/agents");
  const health = page.getByRole("region", { name: "Agent health" });
  await expect(health).toContainText("Degraded");
  await expect(health).toContainText("The latest evaluated data is stale.");
  await expect(page.getByText("A large move was observed in the demo replay.")).toBeVisible();
  await page.getByRole("button", { name: "Older events" }).click();
  await expect(page.getByText("An earlier demo observation.")).toBeVisible();
  await page.getByLabel("Filter advisory activity by agent").selectOption("risk-explainer");
  await expect(page.getByText("No advisory events in this view.")).toBeVisible();
  await expect(page.getByText(/acknowledging or dismissing items are unavailable/)).toBeVisible();
  expect((await context.request.post("/api/v1/agents/events")).status()).toBe(405);
  expect((await context.request.get("/api/v1/agents/events?userId=other")).status()).toBe(400);
});
