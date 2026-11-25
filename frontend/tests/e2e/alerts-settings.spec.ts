import { expect, test, type Page } from "@playwright/test";
import { capture, openDashboard } from "./preview-helpers";

async function navigate(page: Page, title: "Alerts" | "Settings") {
  const menu = page.getByRole("button", { name: "Open navigation" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: title, exact: true }).click();
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
}

test("protects both routes and shares demo preferences and acknowledgements across navigation", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && (url.hostname !== "127.0.0.1" || url.pathname.startsWith("/api/"))) externalRequests.push(url.href);
  });
  await page.goto("/alerts");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
  await openDashboard(page);
  await navigate(page, "Alerts");
  const inbox = page.getByRole("region", { name: "Alert inbox" });
  await expect(inbox.getByRole("heading", { name: "Paper risk limit reached" })).toBeVisible();
  await capture(page, "alerts-desktop");
  await inbox.getByRole("button", { name: "Acknowledge Paper risk limit reached" }).click();
  await expect(inbox.getByRole("button", { name: "Acknowledge Paper risk limit reached" })).toHaveCount(0);
  await page.getByRole("button", { name: "Dismiss notification" }).click();
  await page.getByRole("link", { name: "Manage notifications" }).click();
  await expect(page).toHaveURL(/\/settings#notification-preferences$/);
  await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeFocused();
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, "settings-desktop");
  await page.getByRole("checkbox", { name: "Email digest" }).check();
  await page.getByRole("button", { name: "Save notifications" }).click();
  await expect(page.getByRole("list", { name: "Demo settings audit trail" })).toContainText("Notification preferences updated");
  await page.getByRole("combobox", { name: "Timezone" }).selectOption("UTC");
  const displayName = page.getByRole("textbox", { name: "Demo display name" });
  await displayName.press("Enter");
  await expect(page.getByRole("list", { name: "Demo settings audit trail" })).toContainText("Profile preferences updated");
  await expect(displayName).toBeFocused();

  await page.getByRole("spinbutton", { name: "Daily loss limit (INR)" }).fill("2250.25");
  await page.getByRole("button", { name: "Review risk changes" }).click();
  const dialog = page.getByRole("dialog", { name: "Confirm demo risk limits" });
  await expect(dialog).toContainText("₹2,250.25 daily loss limit");
  await dialog.getByRole("textbox", { name: "Demo verification code" }).fill("246810");
  await dialog.getByRole("button", { name: "Confirm demo change" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("list", { name: "Demo settings audit trail" })).toContainText("Demo risk limits updated");
  await page.getByRole("button", { name: "Dismiss notification" }).click();
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, "settings-desktop-light");

  await navigate(page, "Alerts");
  await expect(page.getByRole("region", { name: "Delivery preferences" })).toContainText("Demo on");
  await expect(inbox).toContainText("UTC");
  await expect(inbox.getByRole("button", { name: "Acknowledge Paper risk limit reached" })).toHaveCount(0);
  await capture(page, "alerts-desktop-light");
  expect(externalRequests).toEqual([]);
});

test("fits phone and tablet and supports keyboard acknowledgement and session confirmation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDashboard(page);
  await navigate(page, "Alerts");
  const ack = page.getByRole("button", { name: "Acknowledge Paper risk limit reached" });
  await expect(ack).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await capture(page, "alerts-mobile");
  await ack.focus();
  await page.keyboard.press("Enter");
  await expect(ack).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Paper risk limit reached" })).toBeFocused();
  await page.getByRole("button", { name: "Dismiss notification" }).click();

  await navigate(page, "Settings");
  const revoke = page.getByRole("button", { name: "Revoke Sample tablet" });
  await expect(revoke).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await capture(page, "settings-mobile");
  await revoke.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Confirm sample session revocation" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(revoke).toBeFocused();
  await revoke.click();
  await dialog.getByRole("textbox", { name: "Demo verification code" }).fill("246810");
  await dialog.getByRole("button", { name: "Confirm demo change" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("list", { name: "Sample sessions" })).toContainText("Revoked");
  await page.getByRole("button", { name: "Dismiss notification" }).click();

  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(768);
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, "settings-tablet");
  await navigate(page, "Alerts");
  await expect(page.getByRole("region", { name: "Alert inbox" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(768);
  await capture(page, "alerts-tablet");
});
