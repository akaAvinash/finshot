import { expect, test } from "@playwright/test";
import { signInStaging } from "./staging-helpers";

const api = "/api/v1";
const origin = "http://127.0.0.1:3101";
const fixture = "http://127.0.0.1:3102/__fixture";
const reads = ["brokers/preview", "strategies/preview", "auto-trading/paper", "reports/paper"];

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${fixture}/reset`)).status()).toBe(204);
});

test("forwards public market data through ingress without sharing account credentials", async ({ context, page, request }) => {
  const overview = await request.get(`${api}/market/overview`, { headers: { "X-Forwarded-For": "192.0.2.9" } });
  expect(overview.status()).toBe(200);
  expect(await overview.json()).toEqual({ source: "demo", quotes: [] });
  expect(overview.headers()["cache-control"]).toContain("no-store");
  expect(overview.headers()["set-cookie"]).toBeUndefined();

  await signInStaging(page);
  const instruments = await context.request.get(`${api}/market/instruments?query=M%26M`, {
    headers: { Authorization: "Bearer local-fixture-token", "X-CSRF-Token": "fixture-proof" },
  });
  expect(instruments.status()).toBe(200);
  expect(await instruments.json()).toMatchObject({ instruments: [{ id: "NSE:M&M" }] });
  const candles = await context.request.get(`${api}/market/instruments/NSE%3AM%26M/candles?timeframe=15m`);
  expect(candles.status()).toBe(200);
  expect(await candles.json()).toMatchObject({ instrumentId: "NSE:M&M", timeframe: "15m", candles: [] });

  const direct = await request.get(`http://127.0.0.1:3103${api}/market/overview`, {
    headers: { "X-Tradeo-Client-IP": "192.0.2.1", "X-Tradeo-Ingress-Token": "forged-proof" },
  });
  expect(direct.status()).toBe(403);
  expect(await direct.json()).toMatchObject({ code: "UNTRUSTED_INGRESS" });
});

test("requires a staging account for workspace reads and keeps the CSV download available", async ({ context, page, request }) => {
  for (const endpoint of reads) {
    const denied = await request.get(`${api}/${endpoint}`);
    expect(denied.status()).toBe(401);
    expect(await denied.json()).toMatchObject({ code: "UNAUTHENTICATED" });
  }

  await signInStaging(page);
  for (const endpoint of reads.slice(0, 3)) {
    const result = await context.request.get(`${api}/${endpoint}`);
    expect(result.status()).toBe(200);
    expect(await result.json()).toMatchObject({ status: "empty" });
    expect(result.headers()["cache-control"]).toContain("no-store");
  }

  const query = "from=2026-11-20&to=2026-11-21";
  const report = await context.request.get(`${api}/reports/paper?${query}`);
  expect(report.status()).toBe(200);
  expect(await report.json()).toMatchObject({ status: "ready", data: { period: { from: "2026-11-20", to: "2026-11-21" } } });
  const csv = await context.request.get(`${api}/reports/paper/trades.csv?${query}`);
  expect(csv.status()).toBe(200);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect(csv.headers()["content-disposition"]).toContain("attachment");

  expect((await request.post(`${fixture}/report/empty`)).status()).toBe(204);
  const emptyReport = await context.request.get(`${api}/reports/paper?${query}`);
  expect(await emptyReport.json()).toEqual({ status: "empty" });
});

test("verifies demo writes at ingress and preserves upstream failures", async ({ context, page, request }) => {
  await signInStaging(page);
  const csrf = await context.request.get(`${api}/auth/csrf`);
  const { csrfToken } = await csrf.json();
  const headers = { Origin: origin, "X-CSRF-Token": csrfToken, "Content-Type": "application/json" };
  const commands = [
    { path: "brokers/preview/zerodha/actions", body: { action: "connect" } },
    { path: "brokers/preview/fyers/actions", body: { action: "disconnect" } },
    { path: "strategies/preview/commands", body: { action: "pause", id: "demo-strategy" } },
    { path: "auto-trading/paper/commands", body: { action: "halt", confirmation: "STOP" } },
  ];
  for (const { path, body } of commands) {
    const result = await context.request.post(`${api}/${path}`, { headers, data: body });
    expect(result.status()).toBe(200);
    expect(await result.json()).toEqual({ received: body });
  }

  const endpoint = `${api}/auto-trading/paper/commands`;
  const wrongOrigin = await context.request.post(endpoint, { headers: { ...headers, Origin: "https://example.com" }, data: { action: "pause" } });
  expect(await wrongOrigin.json()).toMatchObject({ code: "CSRF_FAILED", message: "The request could not be verified." });
  expect(wrongOrigin.status()).toBe(403);
  const staleCsrf = await context.request.post(endpoint, { headers: { ...headers, "X-CSRF-Token": "invalid" }, data: { action: "pause" } });
  expect(staleCsrf.status()).toBe(403);
  expect(await staleCsrf.json()).toMatchObject({ code: "CSRF_FAILED", message: "Auth fixture error" });
  expect((await context.request.post(endpoint, { headers: { ...headers, "Content-Type": "text/plain" }, data: "pause" })).status()).toBe(415);
  expect((await context.request.post(endpoint, { headers, data: "x".repeat(16 * 1024 + 1) })).status()).toBe(413);
  const wrongMethod = await context.request.get(endpoint);
  expect(wrongMethod.status()).toBe(405);
  expect(wrongMethod.headers().allow).toBe("POST");
  expect((await context.request.post(`${api}/auto-trading/live/commands`, { headers, data: { action: "start" } })).status()).toBe(404);
  expect((await request.get(`${api}/market/overview?url=https://example.com`)).status()).toBe(400);

  const offline = await request.get(`${api}/market/instruments?query=fixture-provider-offline`);
  expect(offline.status()).toBe(503);
  expect(await offline.json()).toMatchObject({ code: "MARKET_DATA_UNAVAILABLE" });
  expect(offline.headers()["retry-after"]).toBe("5");
  expect(offline.headers()["x-request-id"]).toBe("market-fixture");
  const badMedia = await request.get(`${api}/market/instruments?query=fixture-invalid-media`);
  expect(badMedia.status()).toBe(502);
  expect(await badMedia.json()).toMatchObject({ code: "API_UNAVAILABLE" });
});
