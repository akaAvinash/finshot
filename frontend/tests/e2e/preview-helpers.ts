import { mkdir } from "node:fs/promises";
import { expect, type Page } from "@playwright/test";

export async function requestCode(page: Page) {
  await page.getByLabel("Mobile number").fill("98765 43210");
  await page.getByRole("button", { name: "Get preview code" }).click();
  await expect(page.getByLabel("One-time code")).toBeVisible();
}

export async function openDashboard(page: Page) {
  await page.goto("/login");
  await requestCode(page);
  await page.getByLabel("One-time code").fill("123456");
  await page.getByRole("button", { name: "Open dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Trading overview" })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
}

export async function capture(page: Page, name: string) {
  if (process.env.TRADEO_CAPTURE_SCREENSHOTS !== "1") return;

  await mkdir("screenshots", { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  await page.getByRole("img", { name: "FinShot", exact: true }).filter({ visible: true }).first()
    .locator("img").evaluate((logo: HTMLImageElement) => logo.decode());
  await page.screenshot({ path: `screenshots/${name}.png`, fullPage: true, animations: "disabled" });
}
