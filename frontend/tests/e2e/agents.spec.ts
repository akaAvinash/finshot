import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

async function openAgents(page: Page) {
  await openDashboard(page);
  const navigation = page.getByRole("button", { name: "Open navigation" });
  if (await navigation.isVisible()) await navigation.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Agents", exact: true }).click();
  await expect(page).toHaveURL(/\/agents$/);
  await expect(page.getByRole("region", { name: "Market Scanner" })).toBeVisible();
}

test("protects Agents and records local advisory controls without API requests", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && (url.hostname !== "127.0.0.1" || url.pathname.startsWith("/api/"))) externalRequests.push(url.href);
  });

  await page.goto("/agents");
  await expect(page).toHaveURL(/\/login$/);
  await openAgents(page);
  await capture(page, "agents-desktop");
  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await capture(page, "agents-desktop-light");

  await page.getByRole("button", { name: "Pause Market Scanner" }).click();
  await expect(page.getByRole("heading", { name: "Observer paused" })).toBeVisible();
  await page.getByRole("button", { name: "Resume Market Scanner" }).click();
  await expect(page.getByRole("heading", { name: "Observer resumed" })).toBeVisible();

  const timeline = page.getByRole("region", { name: "Advisory timeline" });
  const review = timeline.getByRole("button", { name: "Review Signal proposed" });
  await review.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Review signal proposed" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(review).toBeFocused();
  await review.click();
  await dialog.getByRole("button", { name: "Dismiss item" }).click();
  await expect(dialog).toBeHidden();
  await expect(timeline.getByText("Dismissed", { exact: true })).toBeVisible();
  expect(externalRequests).toEqual([]);
});

test("fits phone and tablet and pauses controls when telemetry is stale", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openAgents(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await capture(page, "agents-mobile");
  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(768);
  await capture(page, "agents-tablet");

  await page.getByRole("combobox", { name: "Filter events by agent" }).selectOption("strategy");
  const timeline = page.getByRole("region", { name: "Advisory timeline" });
  await expect(timeline.getByRole("heading", { name: "Signal proposed" })).toBeVisible();
  await expect(timeline.getByRole("heading", { name: "Risk limit applied" })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Agent preview data" }).selectOption("stale");
  await expect(page.getByRole("button", { name: "Pause Market Scanner" })).toBeDisabled();
  await page.getByRole("button", { name: "Load latest agent data" }).click();
  await expect(page.getByRole("button", { name: "Pause Market Scanner" })).toBeEnabled();
});
