import { expect, test, type Page } from "@playwright/test";
import { signInStaging } from "./staging-helpers";

const fixture = "http://127.0.0.1:3102/__fixture";

async function createDraft(page: Page, name: string) {
  await page.goto("/strategies");
  await page.getByRole("button", { name: "Create strategy" }).click();
  await page.getByLabel("Strategy name").fill(name);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("button", { name: `View ${name}` })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
  expect((await request.post(`${fixture}/workspace/enable`)).status()).toBe(204);
});

test("authorizes two same-provider accounts, persists actions by connection ID and shows the stored portfolio", async ({ page, context, request }) => {
  await signInStaging(page);
  expect((await request.post(`${fixture}/expire-step-up`)).status()).toBe(204);
  await page.goto("/brokers");
  const broker = page.getByRole("region", { name: "Sample Broker" });
  await broker.getByRole("button", { name: "Connect demo" }).click();
  const dialog = page.getByRole("dialog", { name: "Authorize Sample Broker?" });
  await dialog.getByRole("button", { name: "Authorize demo account" }).click();
  await dialog.getByLabel("Authenticator code").fill("645721");
  await dialog.getByRole("button", { name: "Verify and continue" }).click();
  await expect(page).toHaveURL(/\/brokers\/callback\?state=/);
  await page.route("**/api/v1/broker-connections/authorizations/callback", (route) => route.fulfill({
    status: 429, headers: { "Retry-After": "2" }, json: { code: "BROKER_RATE_LIMITED", message: "Too many requests." },
  }), { times: 1 });
  await page.getByRole("button", { name: "Complete demo authorization" }).click();
  const retryAuthorization = page.getByRole("button", { name: "Retry demo authorization" });
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Try again in 2 seconds.");
  await expect(page).toHaveURL(/\/brokers\/callback$/);
  await expect(retryAuthorization).toBeDisabled();
  await retryAuthorization.click();
  await expect(page).toHaveURL(/\/brokers$/);
  await expect(broker.getByText("•••• 0248")).toHaveCount(1);

  await broker.getByRole("button", { name: "Connect demo" }).click();
  await dialog.getByRole("button", { name: "Authorize demo account" }).click();
  await page.getByRole("button", { name: "Complete demo authorization" }).click();
  await expect(broker.getByText("•••• 0248")).toHaveCount(2);
  await expect(broker.getByRole("button", { name: "Connect demo" })).toBeDisabled();
  await page.reload();
  await expect(broker.getByText("•••• 0248")).toHaveCount(2);
  const api = "/api/v1/broker-connections";
  const { connections: [firstAccount, secondAccount] } = await (await context.request.get(api)).json();
  expect(firstAccount.connectionId).not.toBe(secondAccount.connectionId);

  await broker.getByRole("listitem").first().getByRole("button", { name: "Sync demo" }).click();
  const sync = page.getByRole("dialog", { name: "Sync •••• 0248?" });
  await request.post(`${fixture}/workspace/reject-broker`);
  await sync.getByRole("button", { name: "Sync demo account" }).click();
  await expect(sync.getByRole("alert")).toContainText("The broker connection changed.");
  await page.route(`**${api}/${firstAccount.connectionId}/actions`, async (route) => {
    expect((await route.fetch()).status()).toBe(200);
    await route.abort();
  }, { times: 1 });
  await sync.getByRole("button", { name: "Sync demo account" }).click();
  await expect(sync.getByRole("alert")).toContainText("Broker connections are refreshing");
  await expect(sync.getByRole("button", { name: "Sync demo account" })).toBeDisabled();
  await sync.getByRole("button", { name: "Close", exact: true }).click();
  await broker.getByRole("listitem").first().getByRole("button", { name: "View portfolio" }).click();
  const portfolio = page.getByRole("region", { name: "Stored portfolio · •••• 0248" });
  await expect(portfolio).toContainText("535.123456");
  await broker.getByRole("listitem").last().getByRole("button", { name: "View portfolio" }).click();
  await expect(portfolio).toContainText("Sync the account to populate the demo portfolio.");
  await expect(portfolio).not.toContainText("535.123456");

  // Hold the snapshot triggered by an expired-sync response until after a disconnect.
  let releaseSnapshot!: () => void;
  let markSnapshotHeld!: () => void;
  const held = new Promise<void>((resolve) => { markSnapshotHeld = resolve; });
  const release = new Promise<void>((resolve) => { releaseSnapshot = resolve; });
  await page.route(`**${api}`, async (route) => {
    const previous = await route.fetch();
    markSnapshotHeld();
    await release;
    // A successful disconnect aborts the old request before it can paint.
    await route.fulfill({ response: previous }).catch(() => undefined);
  }, { times: 1 });
  await page.route(`**${api}/${secondAccount.connectionId}/actions`, (route) => route.fulfill({
    status: 409, json: { code: "BROKER_AUTH_EXPIRED", message: "The demo authorization has expired." },
  }), { times: 1 });
  try {
    await broker.getByRole("listitem").last().getByRole("button", { name: "Sync demo" }).click();
    await sync.getByRole("button", { name: "Sync demo account" }).click();
    await expect(sync.getByRole("alert")).toContainText("authorization has expired");
    await held;
    await sync.getByRole("button", { name: "Cancel" }).click();
    const cancelled = page.waitForEvent("requestfailed", (request) => request.url().endsWith(api));
    await broker.getByRole("listitem").last().getByRole("button", { name: "Disconnect" }).click();
    await page.getByRole("button", { name: "Disconnect demo account" }).click();
    await cancelled;
    await expect(broker.getByText("•••• 0248")).toHaveCount(1);
  } finally {
    releaseSnapshot();
  }
  await page.reload();
  await expect(broker.getByText("•••• 0248")).toHaveCount(1);
  const { connections } = await (await context.request.get(api)).json();
  expect(connections.map((row: { connectionId: string }) => row.connectionId)).toEqual([firstAccount.connectionId]);
});

test("recovers a pending backtest after reload and runs an approved strategy to a paper fill", async ({ page }) => {
  await signInStaging(page);
  await createDraft(page, "Staging NIFTY demo");
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

  const limits = page.getByRole("region", { name: "Paper risk status" });
  await expect(limits).toContainText("₹1,800");
  await expect(limits).toContainText("1 / 8");
  await expect(page.getByRole("button", { name: "Save paper limits" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.getByRole("button", { name: "Pause paper engine" }).click();
  await expect(page.getByRole("button", { name: "Start paper engine" })).toBeEnabled();
  await page.route("**/api/v1/auto-trading/paper", (route) => route.abort());
  await page.getByRole("button", { name: "Start paper engine" }).click();
  await expect(page.getByRole("heading", { name: "Paper data could not refresh" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Pause paper engine" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Paper kill switch" })).toBeEnabled();
  await page.getByRole("button", { name: "Paper kill switch" }).click();
  await page.getByLabel("Type STOP to confirm").fill("STOP");
  const halted = page.waitForResponse((response) => response.url().endsWith("/api/v1/auto-trading/paper/commands"));
  await page.getByRole("button", { name: "Confirm paper halt" }).click();
  expect(await (await halted).json()).toMatchObject({ engine: "halted", risk: { status: "blocked", blockedReason: "HALTED" } });
  await expect(page.getByRole("button", { name: "Clear paper halt" })).toBeVisible();
  await page.unroute("**/api/v1/auto-trading/paper");
  await page.reload();
  await expect(page.getByRole("button", { name: "Clear paper halt" })).toBeVisible();
  const reset = page.waitForResponse((response) => response.url().endsWith("/api/v1/auto-trading/paper/commands"));
  await page.getByRole("button", { name: "Clear paper halt" }).click();
  expect(await (await reset).json()).toMatchObject({ engine: "idle", risk: { status: "approved", blockedReason: null } });
  await expect(page.getByRole("button", { name: "Start paper engine" })).toBeEnabled();
  await page.getByRole("tab", { name: "Trade log" }).click();
  await expect(page.getByRole("rowheader", { name: "NIFTY 50" })).toBeVisible();
});

test("saves bounded paper limits with authenticator confirmation and displays server history", async ({ page, context, request }) => {
  await signInStaging(page);
  expect((await request.post(`${fixture}/expire-step-up`)).status()).toBe(204);
  await page.goto("/auto-trading");
  const panel = page.getByRole("region", { name: "Trade Controls", exact: true });
  const profit = panel.getByLabel("Daily profit cap (₹)");
  const maxTrades = panel.getByLabel("Maximum trades per session");
  await maxTrades.fill("9");
  await panel.getByRole("button", { name: "Save paper limits" }).click();
  await expect(maxTrades).toHaveAttribute("aria-invalid", "true");
  await maxTrades.fill("6");
  await profit.fill("1234.56");
  await panel.getByRole("button", { name: "Save paper limits" }).click();
  await panel.getByLabel("Authenticator code").fill("645721");
  await page.route("**/api/v1/settings/trade-controls", async (route) => {
    expect(route.request().method()).toBe("PUT");
    expect((await route.fetch()).status()).toBe(200);
    await route.abort();
  }, { times: 1 });
  await panel.getByRole("button", { name: "Verify and save" }).click();
  await expect(panel.getByText("Revision 1", { exact: false }).first()).toBeVisible();
  await panel.getByText("Trade Controls history", { exact: true }).click();
  await expect(panel.getByText("Daily profit cap (₹) · Off → 1234.56", { exact: true })).toBeVisible();
  await page.reload();
  await expect(profit).toHaveValue("1234.56");
  await expect(maxTrades).toHaveValue("6");

  const { csrfToken } = await (await context.request.get("/api/v1/auth/csrf")).json();
  const { revision, controls } = await (await context.request.get("/api/v1/settings/trade-controls")).json();
  expect((await context.request.put("/api/v1/settings/trade-controls", {
    headers: { Origin: "http://127.0.0.1:3101", "X-CSRF-Token": csrfToken },
    data: { expectedRevision: revision, controls: { ...controls, tradeLimit: 5 } },
  })).status()).toBe(200);
  await maxTrades.fill("4");
  await panel.getByRole("button", { name: "Save paper limits" }).click();
  await expect(panel.getByRole("alert")).toContainText("The saved limits have changed.");
  await expect(maxTrades).toHaveValue("4");
  await panel.getByRole("button", { name: "Load latest saved limits" }).click();
  await expect(maxTrades).toHaveValue("5");
});

test("an older backtest cannot approve a draft changed while the run was queued", async ({ page, context }) => {
  await signInStaging(page);
  await createDraft(page, "Edited after queue");
  const { csrfToken } = await (await context.request.get("/api/v1/auth/csrf")).json();
  const headers = { Origin: "http://127.0.0.1:3101", "X-CSRF-Token": csrfToken };
  const { data: { strategies: [strategy] } } = await (await context.request.get("/api/v1/strategies/preview")).json();
  const queued = await context.request.post("/api/v1/backtests/preview/runs", { headers, data: {
    strategyId: `${strategy.id}:draft`, instrumentId: "NSE:NIFTY50", from: "2026-10-05", to: "2026-11-23",
    outOfSampleFrom: "2026-10-21", capitalPaise: 50_000_000, feeBps: 8, slippageBps: 5,
  } });
  expect(queued.status()).toBe(202);
  const { id } = await queued.json();
  await page.getByRole("button", { name: "View Edited after queue" }).click();
  await page.getByRole("button", { name: "Edit draft" }).click();
  await page.getByLabel("Position size (%)").fill("6");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("dialog", { name: "Edited after queue" })).toBeVisible();

  await context.request.get(`/api/v1/backtests/preview/runs/${id}`);
  expect(await (await context.request.get(`/api/v1/backtests/preview/runs/${id}`)).json()).toMatchObject({ status: "completed" });
  await page.reload();
  await page.getByRole("button", { name: "View Edited after queue" }).click();
  await expect(page.getByRole("button", { name: "Activate demo" })).toBeDisabled();
  await expect(page.getByText("Backtest · Unavailable")).toBeVisible();
});

test("reconciles a lost backtest response against the server queue before offering another run", async ({ page }) => {
  await signInStaging(page);
  await createDraft(page, "Lost reply test");
  await page.goto("/backtesting");
  await page.route("**/api/v1/backtests/preview/runs", async (route) => {
    const committed = await route.fetch();
    expect(committed.status()).toBe(202);
    await route.abort();
  });
  const submit = page.getByRole("button", { name: "Run demo backtest" });
  await submit.click();
  await expect(submit).toBeDisabled();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The submission could not be confirmed");
  await page.getByRole("button", { name: "Check run queue" }).click();
  const queue = page.getByRole("region", { name: "Run queue" });
  await expect(queue.getByRole("listitem")).toHaveCount(1);
  await expect(queue).toContainText("Completed", { timeout: 12_000 });
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
