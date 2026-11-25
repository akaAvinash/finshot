import { expect, type Page } from "@playwright/test";

export async function requestStagingChallenge(page: Page, email: string) {
  await page.getByLabel("Email address").fill(email);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Six-digit code")).toBeVisible();
}

export async function signInStaging(page: Page, start = "/login") {
  await page.goto(start);
  await expect(page).toHaveURL(/\/login$/);
  await requestStagingChallenge(page, "owner@example.com");
  await page.getByLabel("Six-digit code").fill("728391");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
