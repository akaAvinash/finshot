import { expect, test } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

test("filters the paper report and exports the full selected period as CSV", async ({ page }) => {
  await page.goto("/reports");
  await expect(page).toHaveURL(/\/login$/);
  await openDashboard(page);
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  await expect(page.getByText("Sample data", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Trade journal table" }).getByRole("row")).toHaveCount(8);
  await capture(page, "paper-reports-desktop");

  await page.getByRole("button", { name: /18 Nov 2026, 1 fill/ }).click();
  const journal = page.getByRole("region", { name: "Trade journal table" });
  await expect(journal.getByRole("row")).toHaveCount(2);
  await expect(journal).toContainText("Signal exit");
  await page.getByRole("button", { name: "Clear day" }).click();
  await expect(journal.getByRole("row")).toHaveCount(8);

  await page.getByLabel("From date").fill("2026-11-11");
  await page.getByLabel("To date").fill("2026-11-12");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect(page).toHaveURL(/from=2026-11-11&to=2026-11-12/);
  await expect(journal).toContainText("RELIANCE");
  await expect(journal).not.toContainText("INFY");
  await expect(page.getByRole("region", { name: "Current replay" })).toContainText("INFY");

  const exportResponse = page.waitForResponse((response) => response.url().includes("trades.csv?from=2026-11-11&to=2026-11-12"));
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export period CSV" }).click();
  expect((await downloaded).suggestedFilename()).toBe("tradeo-paper-trades.csv");
  const csv = await (await exportResponse).text();
  expect(csv).toContain("-617.46,stop-loss");
  expect(csv.match(/RELIANCE/g)).toHaveLength(2);
  expect(csv).not.toContain("INFY");
});

test("keeps date controls and a scrollable journal usable on phone and tablet", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDashboard(page);
  await page.goto("/reports");
  const journal = page.getByRole("region", { name: "Trade journal table" });
  await expect(journal).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(await journal.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  await capture(page, "paper-reports-mobile");

  await page.setViewportSize({ width: 820, height: 1180 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(820);
  await capture(page, "paper-reports-tablet");

  await page.goto("/reports?from=2026-11-23&to=2026-11-01");
  await expect(page.getByRole("heading", { name: "Check the report dates" })).toBeVisible();
  await page.getByRole("link", { name: "All dates" }).click();
  await expect(journal).toBeVisible();
  await page.goto("/reports?from=2025-01-01&to=2025-01-02");
  await expect(page.getByText("No fills to show in this journal view.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Current replay" })).toContainText("INFY");
});
