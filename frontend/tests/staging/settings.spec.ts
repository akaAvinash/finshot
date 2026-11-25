import { expect, test } from "@playwright/test";
import { signInStaging } from "./staging-helpers";

const fixture = "http://127.0.0.1:3102/__fixture";
const auth = "/api/v1/auth";
const profile = "/api/v1/settings/profile";
const origin = "http://127.0.0.1:3101";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

test("loads and saves the account profile with bounded writes and recovers from a read failure", async ({ page, context, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signInStaging(page, "/settings");
  expect((await request.post(`${fixture}/fail-profile-read`)).status()).toBe(204);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Couldn’t load profile.");
  await page.getByRole("button", { name: "Retry profile" }).click();
  const name = page.getByLabel("Display name");
  const timezone = page.getByLabel("Timezone");
  await expect(name).toHaveValue("");
  await expect(timezone).toHaveValue("Asia/Kolkata");
  await expect(page.getByText("Demo settings")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Manage alert preferences" })).toHaveAttribute("href", "/alerts#account-alert-preferences");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);

  await name.fill("x".repeat(49));
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("between 1 and 48 characters");
  await name.fill("  Sample Trader  ");
  await timezone.selectOption("UTC");
  const update = page.waitForRequest((candidate) => candidate.url().endsWith(profile) && candidate.method() === "PUT");
  await page.getByRole("button", { name: "Save profile" }).click();
  expect((await update).postDataJSON()).toEqual({ displayName: "Sample Trader", timezone: "UTC" });
  await expect(page.getByText("Profile saved.")).toBeVisible();
  await page.reload();
  await expect(name).toHaveValue("Sample Trader");
  await expect(timezone).toHaveValue("UTC");

  const csrf = await context.request.get(`${auth}/csrf`);
  const { csrfToken } = await csrf.json();
  const headers = { Origin: "https://example.com", "X-CSRF-Token": csrfToken, "Content-Type": "application/json" };
  const rejected = await context.request.put(profile, { headers, data: { displayName: "Changed", timezone: "UTC" } });
  expect(rejected.status()).toBe(403);
  const oversized = await context.request.put(profile, { headers: { ...headers, Origin: origin }, data: "x".repeat(1025) });
  expect(oversized.status()).toBe(413);
  const saved = await context.request.get(profile);
  expect(saved.headers()["cache-control"]).toContain("no-store");
  expect(await saved.json()).toMatchObject({ displayName: "Sample Trader" });
});

test("ends another session after authenticator step-up and keeps the current session signed in", async ({ page, context, request }) => {
  await signInStaging(page);
  expect((await request.post(`${fixture}/add-tablet-session`)).status()).toBe(204);
  expect((await request.post(`${fixture}/expire-step-up`)).status()).toBe(204);
  await page.goto("/settings");
  await expect(page.getByText("Current session", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "End session for Tablet browser" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "End session", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Verify with your authenticator" })).toBeVisible();
  const code = dialog.getByLabel("Authenticator code");
  await expect(code).toBeFocused();
  await code.fill("000000");
  await dialog.getByRole("button", { name: "Verify and continue" }).click();
  await expect(dialog.getByRole("alert")).toContainText("didn’t match");
  await code.fill("645721");
  await dialog.getByRole("button", { name: "Verify and continue" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Active sessions" })).toBeFocused();
  await expect(page.getByText("Tablet browser")).toHaveCount(0);
  await expect(page.getByText("Current session", { exact: true })).toBeVisible();
  const current = await context.request.get(`${auth}/me`);
  expect(current.status()).toBe(200);
  await page.reload();
  await expect(page.getByText("Current session", { exact: true })).toBeVisible();
  await expect(page.getByText("Tablet browser")).toHaveCount(0);
});

test("refreshes CSRF once when the first profile write is rejected", async ({ page, request }) => {
  await signInStaging(page);
  await page.goto("/settings");
  await page.getByLabel("Display name").fill("Sample Trader");
  expect((await request.post(`${fixture}/reject-profile-csrf`)).status()).toBe(204);

  const csrfReads: string[] = [];
  const writes: number[] = [];
  page.on("request", (candidate) => {
    if (candidate.url().endsWith(`${auth}/csrf`)) csrfReads.push(candidate.url());
  });
  page.on("response", (response) => {
    if (response.url().endsWith(profile) && response.request().method() === "PUT") writes.push(response.status());
  });
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("Profile saved.")).toBeVisible();
  expect(csrfReads).toHaveLength(2);
  expect(writes).toEqual([403, 200]);
  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue("Sample Trader");
});

test("rotates recovery codes after step-up and shows the new set once", async ({ page, request }) => {
  await signInStaging(page);
  await page.goto("/settings");
  const opener = page.getByRole("button", { name: "Generate recovery codes" });
  const dialog = page.getByRole("dialog");
  const requests: string[] = [];
  page.on("request", (candidate) => {
    if (candidate.method() === "POST" && candidate.url().endsWith(`${auth}/totp/recovery-codes`)) requests.push(candidate.url());
  });
  await opener.click();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(requests).toHaveLength(0);

  expect((await request.post(`${fixture}/expire-step-up`)).status()).toBe(204);
  await opener.click();
  await expect(dialog.getByText("A new set replaces every previously issued recovery code.")).toBeVisible();
  await dialog.getByRole("button", { name: "Create new codes" }).click();
  await dialog.getByLabel("Authenticator code").fill("645721");
  await dialog.getByRole("button", { name: "Verify and continue" }).click();
  await expect(dialog.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
  expect(requests).toHaveLength(2);
  await expect(dialog.getByRole("heading", { name: "Save your recovery codes" })).toBeFocused();
  await expect(dialog.getByRole("button", { name: "Done" })).toBeDisabled();
  await dialog.getByLabel("I’ve saved my recovery codes.").check();
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(opener).toBeFocused();
  await opener.click();
  await expect(dialog.getByRole("list", { name: "Recovery codes" })).toHaveCount(0);
  await expect(dialog.getByRole("heading", { name: "Replace recovery codes?" })).toBeVisible();
});
