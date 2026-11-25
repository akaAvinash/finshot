import { expect, test, type Page } from "@playwright/test";

const fixture = "http://127.0.0.1:3102/__fixture";
const api = "/api/v1/alerts";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

async function openAccountAlerts(page: Page) {
  await page.goto("/alerts");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Mobile number").fill("98765 43210");
  await page.getByRole("button", { name: "Request code", exact: true }).click();
  await page.getByLabel("One-time code").fill("842615");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/alerts");
  await expect(page.getByText("Account inbox", { exact: true })).toBeVisible();
}

test("uses server cursor and filters, then persists a keyboard acknowledgement", async ({ page, context }) => {
  expect((await context.request.get(api)).status()).toBe(401);
  await openAccountAlerts(page);
  const inbox = page.getByRole("region", { name: "Alert inbox" });
  await expect(inbox.getByRole("heading", { name: "Paper engine halted" })).toBeVisible();
  await expect(page.getByLabel("Account inbox summary")).toContainText("28");
  await page.getByRole("button", { name: "Next alerts page" }).click();
  await expect(inbox.getByRole("heading", { name: "Demo broker connection expired" })).toBeVisible();
  await expect(inbox.getByText("Page 2")).toBeVisible();
  await page.getByRole("button", { name: "Previous alerts page" }).click();
  await expect(inbox.getByRole("heading", { name: "Paper engine halted" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Previous alerts page" })).toBeFocused();

  await page.getByRole("combobox", { name: "Filter alerts by source" }).selectOption("paper");
  await page.getByRole("combobox", { name: "Filter alerts by severity" }).selectOption("critical");
  await page.getByRole("button", { name: "Unread", exact: true }).click();
  await expect(inbox.getByRole("heading", { level: 3 })).toHaveCount(1);
  await page.getByRole("button", { name: "Acknowledge Paper engine halted" }).press("Enter");
  await expect(inbox.getByText("No alerts match this view.")).toBeVisible();
  await expect(inbox.getByRole("heading", { name: "Alert inbox" })).toBeFocused();
  await expect(page.getByLabel("Account inbox summary")).toContainText("27");

  await page.reload();
  const acknowledged = inbox.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Paper engine halted" }) });
  await expect(acknowledged).toContainText("Acknowledged");
});

test("persists optional warning and info settings while critical alerts remain available", async ({ page, context }) => {
  await openAccountAlerts(page);
  const prefs = page.getByRole("region", { name: "Delivery preferences" });
  await expect(prefs.getByText("Always on")).toBeVisible();
  await expect(prefs.getByText("Unavailable", { exact: true })).toHaveCount(3);

  const session = (await context.cookies()).find(({ name }) => name === "__Host-tradeo_session");
  const forged = await context.request.put(`${api}/preferences`, {
    headers: { Cookie: `${session?.name}=${session?.value}`, Origin: "https://example.com", "X-CSRF-Token": "invalid" },
    data: { inApp: { warning: false, info: false } },
  });
  expect(forged.status()).toBe(403);

  await page.getByRole("button", { name: "Next alerts page" }).click();
  await expect(page.getByText("Page 2")).toBeVisible();
  await prefs.getByRole("checkbox", { name: "Warning alerts" }).uncheck();
  await prefs.getByRole("checkbox", { name: "Info alerts" }).uncheck();
  const save = prefs.getByRole("button", { name: "Save alert preferences" });
  await save.press("Enter");
  await expect(page.getByText("Alert preferences saved")).toBeVisible();
  await expect(save).toBeFocused();
  const inbox = page.getByRole("region", { name: "Alert inbox" });
  await expect(inbox.getByRole("heading", { level: 3 })).toHaveCount(2);
  await expect(inbox).toContainText("Paper engine halted");
  await expect(inbox).toContainText("Demo broker connection expired");

  await page.goto("/settings");
  await page.getByRole("link", { name: "Manage alert preferences" }).click();
  await expect(page).toHaveURL(/\/alerts#account-alert-preferences$/);
  await expect(prefs.getByRole("checkbox", { name: "Warning alerts" })).not.toBeChecked();
  await expect(prefs.getByRole("checkbox", { name: "Info alerts" })).not.toBeChecked();
  await expect(prefs.getByText("Always on")).toBeVisible();
});
