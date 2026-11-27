import { expect, test } from "@playwright/test";

const fixture = "http://127.0.0.1:3102/__fixture";
const endpoint = "/api/v1/auth/login/tester";
const phone = "98765 43216";
const invite = "Fixture_Invite-1234567";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

test("requires Origin and CSRF on the tester proxy", async ({ request }) => {
  const response = await request.post(endpoint, { data: { phone: "+919876543216", inviteCode: invite } });
  expect(response.status()).toBe(403);
  expect(await response.json()).toMatchObject({ code: "CSRF_FAILED" });
});

test("redeems a tester invite once, enforces the UI scope, and handles revocation", async ({ page, request }) => {
  expect((await request.post(`${fixture}/workspace/enable`)).status()).toBe(204);
  await page.goto("/login");
  await page.getByRole("button", { name: "Tester invite" }).click();
  await page.getByLabel("Mobile number").fill(phone);
  const code = page.getByLabel("Invite code");
  await expect(code).toHaveAttribute("type", "password");
  await code.fill("Invalid_Invite-1234567");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("The phone number or code is not valid.");

  await code.fill(invite);
  const [login] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith(endpoint) && response.request().method() === "POST"),
    page.getByRole("button", { name: "Sign in", exact: true }).click(),
  ]);
  expect(login.status()).toBe(200);
  expect(await login.headerValue("cache-control")).toContain("no-store");
  const setCookies = await login.headerValues("set-cookie");
  expect(setCookies).toHaveLength(2);
  expect(setCookies.every((value) => /Secure/i.test(value) && /HttpOnly/i.test(value))).toBe(true);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Tester · Paper only")).toBeVisible();
  await expect(page.getByRole("link", { name: "Settings", exact: true })).toHaveCount(0);

  await page.goto("/login/authenticator");
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/brokers/callback");
  await expect(page).toHaveURL(/\/brokers$/);
  await expect(page.getByRole("heading", { name: "Broker connections" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect demo" })).toHaveCount(0);

  await page.goto("/auto-trading");
  await expect(page.getByText("Tester accounts have read-only access to paper limits.")).toBeVisible();
  await expect(page.getByText("Daily loss limit (₹)", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save paper limits", exact: true })).toHaveCount(0);

  await page.goto("/strategies");
  await page.getByRole("button", { name: "Create strategy" }).click();
  await page.getByLabel("Strategy name").fill("Tester NIFTY demo");
  await page.getByRole("button", { name: "Save draft" }).click();
  await page.getByRole("button", { name: "View Tester NIFTY demo" }).click();
  await page.getByRole("link", { name: "Open Backtesting" }).click();
  await page.getByRole("button", { name: "Run demo backtest" }).click();
  await expect(page.getByRole("region", { name: "Run queue" })).toContainText("Completed", { timeout: 12_000 });
  await page.goto("/strategies");
  await page.getByRole("button", { name: "View Tester NIFTY demo" }).click();
  await page.getByRole("button", { name: "Activate demo" }).click();
  await expect(page.getByRole("button", { name: "Pause demo" })).toBeEnabled();

  await page.goto("/auto-trading");
  await page.getByLabel("Assigned strategy").selectOption({ label: "Tester NIFTY demo · NIFTY 50" });
  await page.getByRole("button", { name: "Start paper engine" }).click();
  await expect(page.getByRole("button", { name: "Pause paper engine" })).toBeVisible();
  await page.getByRole("button", { name: "Paper kill switch" }).click();
  await page.getByLabel("Type STOP to confirm").fill("STOP");
  await page.getByRole("button", { name: "Confirm paper halt" }).click();
  await expect(page.getByRole("button", { name: "Clear paper halt" })).toBeEnabled();

  expect((await request.post(`${fixture}/tester/revoke`)).status()).toBe(204);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole("button", { name: "Tester invite" }).click();
  await page.getByLabel("Mobile number").fill(phone);
  await page.getByLabel("Invite code").fill(invite);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("The phone number or code is not valid.");
});
