import { expect, test } from "@playwright/test";

const auth = "/api/v1/auth";
const origin = "http://127.0.0.1:3101";
const secureCookieOrigin = "https://127.0.0.1:3101";

test("requires backend sign-in, preserves rotated cookies, and revokes the session on sign-out", async ({ page, context }) => {
  await context.addCookies([{ name: "tradeo-preview-session", value: "phase-1", url: origin }]);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Staging sign-in" })).toBeVisible();
  await expect(page.getByText("123456")).toHaveCount(0);

  await page.getByLabel("Mobile number").fill("98765 43210");
  await page.getByRole("button", { name: "Request code", exact: true }).click();
  await expect(page.getByText("Code requested for the number ending in 3210.")).toBeVisible();
  await page.getByLabel("One-time code").fill("123456");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  const loginError = page.getByRole("main").getByRole("alert");
  await expect(loginError).toContainText("invalid, expired, or used");

  await page.getByRole("button", { name: "Request a new code" }).click();
  await expect(loginError).toHaveCount(0);
  await page.getByLabel("One-time code").fill("842615");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Staging session")).toBeVisible();

  const authCookies = (await context.cookies()).filter(({ name }) => name.startsWith("__Host-tradeo_"));
  expect(authCookies.map(({ name }) => name).sort()).toEqual(["__Host-tradeo_csrf", "__Host-tradeo_session"]);
  for (const cookie of authCookies) expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax", path: "/" });
  expect((await context.cookies()).some(({ name }) => name === "fixture-unrelated")).toBe(false);
  expect(await page.evaluate(async (path) => (await fetch(path)).status, `${auth}/me`)).toBe(200);
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/markets$/);

  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.cookies()).filter(({ name }) => name.startsWith("__Host-tradeo_"))).toHaveLength(0);
  const sessionCookie = authCookies.find(({ name }) => name === "__Host-tradeo_session")!;
  const revoked = await context.request.get(`${auth}/me`, { headers: { Cookie: `${sessionCookie.name}=${sessionCookie.value}` } });
  expect(revoked.status()).toBe(401);
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/login$/);
});

test("surfaces throttling and unavailable delivery without signing in", async ({ page }) => {
  await page.goto("/login");
  const phone = page.getByLabel("Mobile number");
  const requestCode = page.getByRole("button", { name: "Request code", exact: true });
  const loginError = page.getByRole("main").getByRole("alert");
  await phone.fill("98765 43211");
  await requestCode.click();
  await expect(loginError).toHaveText("Too many attempts. Try again in 30 seconds.");
  await phone.fill("98765 43212");
  await requestCode.click();
  await expect(loginError).toHaveText("Code delivery is unavailable. Try again later.");
  await expect(page).toHaveURL(/\/login$/);
});

test("limits the proxy to configured auth routes and fails closed on session validation", async ({ page, context }) => {
  const csrf = await context.request.get(`${auth}/csrf`, { headers: { "X-Forwarded-For": "192.0.2.8" } });
  expect(csrf.status()).toBe(200);
  expect(csrf.headers()["cache-control"]).toBe("no-store");
  const { csrfToken } = await csrf.json();
  const headers = { Origin: origin, "X-CSRF-Token": csrfToken, "Content-Type": "application/json" };
  const foreign = await context.request.post(`${auth}/otp/request`, { headers: { ...headers, Origin: "https://example.com" }, data: { phone: "+919876543210" } });
  expect(foreign.status()).toBe(403);
  const missingOrigin = await context.request.post(`${auth}/otp/request`, { headers: { "X-CSRF-Token": csrfToken }, data: { phone: "+919876543210" } });
  expect(missingOrigin.status()).toBe(403);
  expect((await context.request.post(`${auth}/otp/request`, { headers, data: "x".repeat(1025) })).status()).toBe(413);
  expect((await context.request.get(`${auth}/otp/verify`)).status()).toBe(405);
  expect((await context.request.get(`${auth}/sessions`)).status()).toBe(404);

  await context.addCookies([{ name: "__Host-tradeo_session", value: "not-a-session", url: secureCookieOrigin, httpOnly: true }]);
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Request code" })).toBeVisible();

  await context.addCookies([{ name: "__Host-tradeo_session", value: "upstream-offline", url: secureCookieOrigin, httpOnly: true }]);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Sign-in is temporarily unavailable");
  await expect(page.getByRole("button", { name: "Request code" })).toHaveCount(0);
});
