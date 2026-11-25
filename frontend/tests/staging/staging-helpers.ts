import { expect, type Page } from "@playwright/test";

export async function signInStaging(page: Page, start = "/login") {
  await page.goto(start);
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Mobile number").fill("98765 43218");
  await page.getByLabel("Authenticator code").fill("728391");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
