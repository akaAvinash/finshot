import { expect, test, type Page } from "@playwright/test";

const fixture = "http://127.0.0.1:3102/__fixture";
const csvPath = "/api/v1/reports/paper/trades.csv";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

async function signIn(page: Page) {
  await page.goto("/reports");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Mobile number").fill("98765 43210");
  await page.getByRole("button", { name: "Request code", exact: true }).click();
  await page.getByLabel("One-time code").fill("842615");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("loads authenticated paper ledger totals and downloads server CSV for the same dates", async ({ page, context }) => {
  expect((await context.request.get(csvPath)).status()).toBe(401);
  await signIn(page);
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Reports" }).click();
  await expect(page.getByText("Paper trading", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Paper report totals")).toContainText("+₹64.00");
  await expect(page.getByRole("region", { name: "By strategy version" })).toContainText("Staging ledger · v3");
  await expect(page.getByRole("region", { name: "Current replay" })).toContainText("Matched");

  await page.getByLabel("From date").fill("2026-11-13");
  await page.getByRole("button", { name: "Apply dates" }).click();
  const journal = page.getByRole("region", { name: "Trade journal table" });
  await expect(journal.getByRole("row")).toHaveCount(2);
  await expect(journal).toContainText("Sell");

  const responsePromise = page.waitForResponse((response) => response.url().includes(`${csvPath}?from=2026-11-13`));
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export period CSV" }).click();
  expect((await downloadPromise).suggestedFilename()).toBe("tradeo-paper-trades.csv");
  const response = await responsePromise;
  expect(response.headers()["cache-control"]).toContain("no-store");
  const csv = await response.text();
  expect(csv).toContain("64.00,signal-exit,staging-sell");
  expect(csv).not.toContain("staging-buy");

  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.request.get(csvPath)).status()).toBe(401);
  await page.goto("/reports");
  await expect(page).toHaveURL(/\/login$/);
});

test("handles an empty ledger, reconciliation mismatch, and report or CSV outage", async ({ page, request }) => {
  await signIn(page);
  const mode = async (name: string) => expect((await request.post(`${fixture}/report/${name}`)).status()).toBe(204);
  await mode("empty");
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "No paper report yet" })).toBeVisible();

  await mode("mismatch");
  await page.reload();
  await expect(page.getByRole("region", { name: "Current replay" }).getByRole("alert")).toContainText("Ledger cash");

  await mode("unavailable");
  await page.getByRole("button", { name: "Export period CSV" }).click();
  await expect(page.getByText("CSV export failed. Try again.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Paper report unavailable" })).toBeVisible();

  await mode("ready");
  await page.getByRole("button", { name: "Retry report" }).click();
  await expect(page.getByRole("heading", { name: "Trade journal" })).toBeVisible();
});
