import { expect, test, type Page } from "@playwright/test";
import { requestStagingChallenge } from "./staging-helpers";

const auth = "/api/v1/auth";
const origin = "http://127.0.0.1:3101";
const secureCookieOrigin = "https://127.0.0.1:3101";
const fixture = "http://127.0.0.1:3102/__fixture";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

async function requestCode(page: Page, email: string) {
  return page.evaluate(async ({ auth, email }) => {
    const csrfResponse = await fetch(`${auth}/csrf`);
    if (!csrfResponse.ok) throw new Error(`CSRF request failed: ${csrfResponse.status}`);
    const { csrfToken } = await csrfResponse.json();
    const response = await fetch(`${auth}/otp/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ email }),
    });
    return response.status;
  }, { auth, email });
}

test("requires backend sign-in, preserves rotated cookies, and revokes the session after a sign-out retry", async ({ page, context, request }) => {
  await context.addCookies([{ name: "tradeo-preview-session", value: "phase-1", url: origin }]);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Staging sign-in" })).toBeVisible();
  await expect(page.getByText("123456")).toHaveCount(0);

  const code = page.getByLabel("Six-digit code");
  const signIn = page.getByRole("button", { name: "Sign in", exact: true });
  const loginError = page.getByRole("main").getByRole("alert");
  await requestStagingChallenge(page, "unknown@example.com");
  await code.fill("728391");
  await signIn.click();
  await expect(loginError).toContainText("That code didn’t work.");
  await page.getByRole("button", { name: "Use a different email" }).click();
  await requestStagingChallenge(page, "Owner@Example.com");
  await expect(page.getByText("Signing in as owner@example.com.")).toBeVisible();
  await code.fill("000000");
  await signIn.click();
  await expect(loginError).toContainText("That code didn’t work.");
  await code.fill("728391");
  await signIn.click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Staging session")).toBeVisible();

  const authCookies = (await context.cookies()).filter(({ name }) => name.startsWith("__Host-tradeo_"));
  expect(authCookies.map(({ name }) => name).sort()).toEqual(["__Host-tradeo_csrf", "__Host-tradeo_session"]);
  for (const cookie of authCookies) expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Lax", path: "/" });
  expect((await context.cookies()).some(({ name }) => name === "fixture-unrelated")).toBe(false);
  expect(await page.evaluate(async (path) => (await fetch(path)).status, `${auth}/me`)).toBe(200);
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/markets$/);

  expect((await request.post(`${fixture}/fail-next-logout`)).status()).toBe(204);
  const signOut = page.getByRole("button", { name: "Sign out", exact: true });
  await signOut.click();
  await expect(page.getByText("We couldn’t confirm sign-out. Try again.")).toBeVisible();
  await expect(page).toHaveURL(/\/markets$/);
  await expect(page.getByText("Staging session")).toBeVisible();
  expect(await page.evaluate(async (path) => (await fetch(path)).status, `${auth}/me`)).toBe(200);

  await signOut.click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.cookies()).filter(({ name }) => name.startsWith("__Host-tradeo_"))).toHaveLength(0);
  const sessionCookie = authCookies.find(({ name }) => name === "__Host-tradeo_session")!;
  const revoked = await context.request.get(`${auth}/me`, { headers: { Cookie: `${sessionCookie.name}=${sessionCookie.value}` } });
  expect(revoked.status()).toBe(401);
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/login$/);
});

test("verifies first-time email, enrols with a local QR, then signs in using a fresh authenticator code", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  const emailRequest = page.waitForRequest((request) => request.url().endsWith(`${auth}/otp/request`));
  await requestStagingChallenge(page, "new@example.com");
  expect((await emailRequest).postDataJSON()).toEqual({ email: "new@example.com" });

  const emailCode = page.getByLabel("Six-digit code");
  const verify = page.getByRole("button", { name: "Sign in", exact: true });
  await emailCode.fill("000000");
  await verify.click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("That code didn’t work.");
  await page.getByRole("button", { name: "Start a new sign-in" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await emailCode.fill("842615");
  await verify.click();
  await expect(page).toHaveURL(/\/login\/authenticator$/);
  await expect(page.getByRole("heading", { name: "Set up your authenticator" })).toBeVisible();
  expect(await page.evaluate(async () => new URL((await fetch("/dashboard")).url).pathname)).toBe("/login/authenticator");

  const extraCsrfReads: string[] = [];
  const trackCsrf = (request: import("@playwright/test").Request) => {
    if (request.url().endsWith(`${auth}/csrf`)) extraCsrfReads.push(request.url());
  };
  page.on("request", trackCsrf);
  await page.getByRole("button", { name: "Start authenticator setup" }).click();
  const qr = page.getByRole("img", { name: "Tradeo authenticator setup QR code" });
  await expect(qr).toBeVisible();
  await expect.poll(() => qr.evaluate((node: HTMLCanvasElement) =>
    node.getContext("2d")?.getImageData(0, 0, node.width, node.height).data.some((value, index) => index % 4 === 0 && value === 0),
  )).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  const setupKey = page.locator("#manual-setup-key");
  await expect(setupKey).toBeHidden();
  await page.getByRole("button", { name: "Show setup key" }).click();
  await expect(setupKey).toHaveText(/^[A-Z2-7]{32}$/);
  await page.getByRole("button", { name: "Hide setup key" }).click();
  await expect(setupKey).toBeHidden();

  const setupCode = page.getByLabel("Authenticator code");
  await setupCode.fill("000000");
  await page.getByRole("button", { name: "Confirm authenticator" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The code is invalid or expired");
  await setupCode.fill("615408");
  await page.getByRole("button", { name: "Confirm authenticator" }).click();
  const codes = page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem");
  await expect(codes).toHaveCount(10);
  const continueButton = page.getByRole("button", { name: "Continue to dashboard" });
  await expect(continueButton).toBeDisabled();
  await page.getByLabel("I’ve saved my recovery codes.").check();
  await continueButton.click();
  await expect(page).toHaveURL(/\/dashboard$/);
  page.off("request", trackCsrf);
  expect(extraCsrfReads).toHaveLength(0);

  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await requestStagingChallenge(page, "new@example.com");
  await page.getByLabel("Six-digit code").fill("615408");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("That code didn’t work.");
  await page.getByLabel("Six-digit code").fill("615409");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("uses one recovery proof and requires a replacement authenticator", async ({ page }) => {
  await page.goto("/login");
  await requestStagingChallenge(page, "owner@example.com");
  await page.getByRole("button", { name: "Use a recovery code" }).click();
  await page.getByLabel("Recovery code").fill("ABCDE-FGHIJ");
  const proof = page.waitForRequest((request) => request.url().endsWith(`${auth}/otp/verify`));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await proof).postDataJSON()).toEqual({ challengeId: expect.any(String), recoveryCode: "ABCDE-FGHIJ" });
  await expect(page).toHaveURL(/\/login\/authenticator$/);
  await page.goto("/alerts");
  await expect(page).toHaveURL(/\/login\/authenticator$/);
  await page.getByRole("button", { name: "Start authenticator setup" }).click();
  await page.getByLabel("Authenticator code").fill("615408");
  await page.getByRole("button", { name: "Confirm authenticator" }).click();
  await expect(page.getByRole("heading", { name: "Save your recovery codes" })).toBeFocused();
  await expect(page.getByRole("list", { name: "Recovery codes" })).not.toContainText("abcde-fghij");
  await page.getByLabel("I’ve saved my recovery codes.").check();
  await page.getByRole("button", { name: "Continue to dashboard" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("list", { name: "Recovery codes" })).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await requestStagingChallenge(page, "owner@example.com");
  await page.getByRole("button", { name: "Use a recovery code" }).click();
  await page.getByLabel("Recovery code").fill("abcde-fghij");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("That code didn’t work.");
});

test("preserves retry deadlines when switching verification methods and shows delivery errors", async ({ page }) => {
  await page.goto("/login");
  const loginError = page.getByRole("main").getByRole("alert");
  await page.getByLabel("Email address").fill("down@example.com");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(loginError).toHaveText("Sign-in is unavailable because codes can’t be sent right now. Try again later.");

  await requestStagingChallenge(page, "verify-limited@example.com");
  const attempts: string[] = [];
  page.on("request", (request) => { if (request.url().endsWith(`${auth}/otp/verify`)) attempts.push(request.url()); });
  await page.getByLabel("Six-digit code").fill("728391");
  const signIn = page.getByRole("button", { name: "Sign in", exact: true });
  await signIn.click();
  await expect(loginError).toHaveText("Too many attempts. Try again in 30 seconds.");
  await signIn.click();
  await expect(loginError).toHaveText(/^Try again in \d+ seconds\.$/);
  expect(attempts).toHaveLength(1);
  await page.getByRole("button", { name: "Use a recovery code" }).click();
  await page.getByLabel("Recovery code").fill("abcde-fghij");
  await signIn.click();
  await expect(loginError).toHaveText(/^Try again in \d+ seconds\.$/);
  expect(attempts).toHaveLength(1);
  await page.getByRole("button", { name: "Use a six-digit code" }).click();
  await page.getByLabel("Six-digit code").fill("728391");
  await signIn.click();
  await expect(loginError).toHaveText(/^Try again in \d+ seconds\.$/);
  expect(attempts).toHaveLength(1);
  await expect(page).toHaveURL(/\/login$/);
});

test("limits the proxy to configured auth routes and fails closed on session validation", async ({ page, context }) => {
  const direct = await context.request.get(`http://127.0.0.1:3103${auth}/csrf`, {
    headers: { "X-Tradeo-Client-IP": "192.0.2.9", "X-Tradeo-Ingress-Token": "forged-proof", "X-Forwarded-For": "192.0.2.8" },
  });
  expect(direct.status()).toBe(403);
  expect((await direct.json()).code).toBe("UNTRUSTED_INGRESS");

  const csrf = await context.request.get(`${auth}/csrf`, { headers: { "X-Forwarded-For": "192.0.2.8" } });
  expect(csrf.status()).toBe(200);
  expect(csrf.headers()["cache-control"]).toBe("no-store");
  const { csrfToken } = await csrf.json();
  const headers = { Origin: origin, "X-CSRF-Token": csrfToken, "Content-Type": "application/json" };
  const foreign = await context.request.post(`${auth}/otp/request`, { headers: { ...headers, Origin: "https://example.com" }, data: { email: "owner@example.com" } });
  expect(foreign.status()).toBe(403);
  const missingOrigin = await context.request.post(`${auth}/otp/request`, { headers: { "X-CSRF-Token": csrfToken }, data: { email: "owner@example.com" } });
  expect(missingOrigin.status()).toBe(403);
  expect((await context.request.post(`${auth}/otp/request`, { headers, data: "x".repeat(1025) })).status()).toBe(413);
  expect((await context.request.get(`${auth}/otp/verify`)).status()).toBe(405);
  expect((await context.request.post(`${auth}/login/totp`, { headers })).status()).toBe(404);
  expect((await context.request.get(`${auth}/sessions`)).status()).toBe(404);

  await context.addCookies([{ name: "__Host-tradeo_session", value: "not-a-session", url: secureCookieOrigin, httpOnly: true }]);
  await page.goto("/markets");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeVisible();

  await context.addCookies([{ name: "__Host-tradeo_session", value: "upstream-offline", url: secureCookieOrigin, httpOnly: true }]);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Sign-in is temporarily unavailable");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
});

test("throttles one ingress client without blocking another and ignores forged IP headers", async ({ page, browser }) => {
  await page.setExtraHTTPHeaders({ "X-Fixture-Client": "limited", "X-Forwarded-For": "192.0.2.9" });
  await page.goto("/login");
  expect(await requestCode(page, "first@example.com")).toBe(202);
  expect(await requestCode(page, "second@example.com")).toBe(202);

  await page.setExtraHTTPHeaders({
    "X-Fixture-Client": "limited",
    "X-Forwarded-For": "192.0.2.10",
    "X-Tradeo-Client-IP": "192.0.2.10",
  });
  expect(await requestCode(page, "third@example.com")).toBe(429);

  const other = await browser.newContext({ baseURL: origin, extraHTTPHeaders: { "X-Fixture-Client": "independent" } });
  try {
    const otherPage = await other.newPage();
    await otherPage.goto("/login");
    expect(await requestCode(otherPage, "third@example.com")).toBe(202);
  } finally {
    await other.close();
  }
});
