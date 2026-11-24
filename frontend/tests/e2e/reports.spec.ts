import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

async function openReports(page: Page) {
  await openDashboard(page);
  const nav = page.getByRole("button", { name: "Open navigation" });
  if (await nav.isVisible()) await nav.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Reports", exact: true }).click();
  await expect(page).toHaveURL(/\/reports$/);
  await expect(page.getByRole("heading", { name: "Trade journal" })).toBeVisible();
}

test("protects Reports and downloads demo CSV and PDF for the selected period", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && (url.hostname !== "127.0.0.1" || url.pathname.startsWith("/api/"))) externalRequests.push(url.href);
  });

  await page.goto("/reports");
  await expect(page).toHaveURL(/\/login$/);
  await openReports(page);
  await expect(page.getByRole("group", { name: "Demo cumulative realized P&L chart" }).locator("canvas").first()).toBeVisible();
  await capture(page, "reports-desktop");
  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await capture(page, "reports-desktop-light");

  await page.getByRole("button", { name: "7 days" }).click();
  await expect(page.getByText("17 Nov 2026 to 23 Nov 2026 IST")).toBeVisible();
  await page.getByRole("button", { name: /23 Nov 2026, 2 closed trades/ }).click();
  await expect(page.getByRole("region", { name: "Trade journal", exact: true })).toContainText("2 closed trades");

  const csvEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export trades CSV" }).click();
  const csv = await csvEvent;
  expect(csv.suggestedFilename()).toBe("tradeo-demo-trades-2026-11-17-2026-11-23.csv");
  const rows = (await readFile(await csv.path(), "utf8")).trim().split("\r\n");
  expect(rows.length).toBeGreaterThan(3);
  expect(rows[1]).toContain('"DEMO","demo"');

  const pdfEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download PDF" }).click();
  const pdf = await pdfEvent;
  expect(pdf.suggestedFilename()).toBe("tradeo-demo-report-2026-11-17-2026-11-23.pdf");
  const bytes = await readFile(await pdf.path());
  expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
  expect(bytes.toString()).toContain("Tradeo demo performance report");
  expect(externalRequests).toEqual([]);
});

test("fits phone and tablet and keeps the calendar and journal keyboard-accessible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openReports(page);
  await capture(page, "reports-mobile");
  const day = page.getByRole("button", { name: /23 Nov 2026, 2 closed trades/ });
  await day.focus();
  await page.keyboard.press("Enter");
  await expect(day).toHaveAttribute("aria-pressed", "true");
  const table = page.getByRole("region", { name: "Demo trade journal table" });
  await table.focus();
  await expect(table).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(768);
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, "reports-tablet");
});
