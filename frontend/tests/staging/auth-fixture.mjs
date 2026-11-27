import { randomBytes, randomUUID } from "node:crypto";
import { createServer, request as httpRequest } from "node:http";
import { isIP } from "node:net";
import { stagingReport, stagingReportCsv } from "./paper-report-fixture.mjs";
import { stagingCandles, stagingInstruments, stagingOverview } from "./market-fixture.mjs";
import { createAlertsFixture, isAlertsFixtureRequest } from "./alerts-fixture.mjs";
import { createWorkspaceFixture } from "./workspace-fixture.mjs";

const publicOrigin = "http://127.0.0.1:3101";
const sessionName = "__Host-tradeo_session";
const csrfName = "__Host-tradeo_csrf";
const cookieAttrs = "Secure; HttpOnly; SameSite=Lax; Path=/";
const sessions = new Map();
const challenges = new Map();
const otpRequestsByIp = new Map();
let failNextLogout = false;
let failNextProfileRead = false;
let rejectNextProfileCsrf = false;
let reportMode = "ready";
let marketMode = "ready";
let alerts = createAlertsFixture();
let workspaceFixture;
const returningNumber = "+919876543218";
const registrationNumber = "+919876543219";
const accountRows = new Map();
const after = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();

function newRecoveryCodes() {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const codes = new Set();
  while (codes.size < 10) {
    const value = Array.from(randomBytes(10), (byte) => alphabet[byte & 31]).join("");
    codes.add(`${value.slice(0, 5)}-${value.slice(5)}`);
  }
  return [...codes];
}

function resetAccounts() {
  accountRows.clear();
  for (const number of [returningNumber, registrationNumber]) {
    accountRows.set(number, { id: randomUUID(), phoneMasked: `+91******${number.slice(-4)}`, displayName: null,
      createdAt: after(0), timezone: "Asia/Kolkata", totpEnabled: number === returningNumber, pending: false, lastCode: null,
      recoveryCodes: number === returningNumber ? ["ABCDE-FGHIJ", "KLMNO-PQRST"] : [] });
  }
}
resetAccounts();
const ingressToken = process.env.TRADEO_AUTH_INGRESS_TOKEN;
if (!ingressToken) throw new Error("Missing test ingress token");

const fixtureAddresses = new Map([
  ["primary", "192.0.2.1"],
  ["limited", "192.0.2.2"],
  ["independent", "2001:db8::3"],
]);

const workspaceReads = new Set(["/api/v1/brokers/preview", "/api/v1/strategies/preview", "/api/v1/auto-trading/paper",
  "/api/v1/backtests/preview", "/api/v1/agents", "/api/v1/agents/health", "/api/v1/agents/events"]);
const workspaceCommands = new Set([
  "/api/v1/brokers/preview/zerodha/actions", "/api/v1/brokers/preview/fyers/actions",
  "/api/v1/strategies/preview/commands", "/api/v1/auto-trading/paper/commands",
  "/api/v1/backtests/preview/runs",
]);

createServer((incoming, response) => {
  const headers = { ...incoming.headers };
  const clientIp = fixtureAddresses.get(headers["x-fixture-client"]) ?? fixtureAddresses.get("primary");
  delete headers["x-fixture-client"];
  delete headers["x-forwarded-for"];
  headers["x-tradeo-client-ip"] = clientIp;
  headers["x-tradeo-ingress-token"] = ingressToken;

  const upstream = httpRequest({ hostname: "127.0.0.1", port: 3103, path: incoming.url, method: incoming.method, headers }, (result) => {
    response.writeHead(result.statusCode, result.headers);
    result.pipe(response);
  });
  upstream.on("error", () => response.destroy());
  incoming.pipe(upstream);
}).listen(3101, "127.0.0.1");

function json(response, status, value, headers = {}) {
  response.writeHead(status, { "Content-Type": "application/json", ...headers });
  response.end(JSON.stringify(value));
}

function error(response, status, code, headers) {
  json(response, status, { code, message: "Auth fixture error" }, headers);
}

function cookie(name, value) {
  return `${name}=${value}; ${cookieAttrs}`;
}

function sessionPayload(account, session) {
  const { id, phoneMasked, displayName, createdAt, totpEnabled } = account;
  return { user: { id, phoneMasked, displayName, createdAt, totpEnabled },
    session: { idleExpiresAt: after(30), expiresAt: after(180), stepUpUntil: session.stepUpUntil } };
}

function startSession(response, phone, previousId, steppedUp) {
  sessions.delete(previousId);
  const id = randomUUID();
  const session = { phone, stepUpUntil: steppedUp ? after(10) : null, deviceLabel: "Current browser", createdAt: after(0) };
  sessions.set(id, session);
  const token = `ses.${id}`;
  return json(response, 200, { ...sessionPayload(accountRows.get(phone), session), csrfToken: token }, {
    "Set-Cookie": [cookie(sessionName, id), cookie(csrfName, token)],
  });
}

createServer(async (request, response) => {
  if (request.url === "/health") return json(response, 200, { ok: true });
  if (request.method === "POST" && request.url === "/__fixture/reset") {
    sessions.clear();
    challenges.clear();
    otpRequestsByIp.clear();
    resetAccounts();
    failNextLogout = false;
    failNextProfileRead = false;
    rejectNextProfileCsrf = false;
    reportMode = "ready";
    marketMode = "ready";
    alerts = createAlertsFixture();
    workspaceFixture = undefined;
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/workspace/enable") {
    workspaceFixture = createWorkspaceFixture();
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/workspace/reject-broker") {
    workspaceFixture?.rejectNextBrokerCommand();
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/fail-next-logout") {
    failNextLogout = true;
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/expire-step-up") {
    for (const session of sessions.values()) {
      if (session.stepUpUntil) session.stepUpUntil = after(-1);
    }
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/fail-profile-read") {
    failNextProfileRead = true;
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/reject-profile-csrf") {
    rejectNextProfileCsrf = true;
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/add-tablet-session") {
    sessions.set(randomUUID(), { phone: returningNumber, stepUpUntil: null, deviceLabel: "Tablet browser", createdAt: after(-1) });
    return response.writeHead(204).end();
  }

  const url = new URL(request.url, publicOrigin);
  if (request.method === "POST" && /^\/__fixture\/report\/(ready|empty|unavailable|mismatch|large)$/.test(url.pathname)) {
    reportMode = url.pathname.split("/").at(-1);
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && /^\/__fixture\/market\/(ready|empty|stale|unavailable|bad-candles|no-quotes)$/.test(url.pathname)) {
    marketMode = url.pathname.split("/").at(-1);
    return response.writeHead(204).end();
  }

  const endpoint = request.url?.replace(/^\/api\/v1\/auth\//, "");
  const cookies = Object.fromEntries((request.headers.cookie ?? "").split("; ").filter(Boolean).map((item) => item.split("=", 2)));
  const sessionId = cookies[sessionName];
  const session = sessions.get(sessionId);
  const signedIn = Boolean(session);
  const csrfToken = cookies[csrfName];
  const clientIp = request.headers["x-forwarded-for"];

  const marketRead = request.method === "GET" && url.pathname.startsWith("/api/v1/market/");
  const workspaceRead = request.method === "GET" && (workspaceReads.has(url.pathname) || url.pathname.startsWith("/api/v1/backtests/preview/runs/"));
  const workspaceCommand = request.method === "POST" && workspaceCommands.has(url.pathname);
  if (marketRead || workspaceRead || workspaceCommand) {
    if (clientIp !== fixtureAddresses.get("primary") || request.headers["x-tradeo-client-ip"] || request.headers["x-tradeo-ingress-token"]) {
      return error(response, 400, "UNEXPECTED_HEADERS");
    }
    const allowedCookies = marketRead ? [] : workspaceCommand ? [sessionName, csrfName] : [sessionName];
    if (Object.keys(cookies).some((name) => !allowedCookies.includes(name))) return error(response, 400, "UNEXPECTED_HEADERS");
    if (marketRead) {
      if (request.headers.authorization || request.headers.origin || request.headers["x-csrf-token"]) {
        return error(response, 400, "UNEXPECTED_HEADERS");
      }
      if (marketMode === "unavailable") return error(response, 503, "MARKET_DATA_UNAVAILABLE");
      if (url.pathname === "/api/v1/market/overview") {
        return json(response, 200, stagingOverview(marketMode), { "Set-Cookie": "fixture-unrelated=ignored; Path=/" });
      }
      if (url.pathname === "/api/v1/market/instruments") {
        const query = url.searchParams.get("query");
        if (query === "fixture-invalid-media") {
          return response.writeHead(502, { "Content-Type": "text/html" }).end("Unexpected HTML response");
        }
        if (query === "fixture-provider-offline") {
          return error(response, 503, "MARKET_DATA_UNAVAILABLE", { "Retry-After": "5", "X-Request-Id": "market-fixture" });
        }
        return json(response, 200, stagingInstruments(query));
      }
      const candleId = /^\/api\/v1\/market\/instruments\/([^/]+)\/candles$/.exec(url.pathname)?.[1];
      if (candleId) {
        const result = stagingCandles(decodeURIComponent(candleId), url.searchParams.get("timeframe"), marketMode);
        if (!result) return error(response, 404, "UNKNOWN_INSTRUMENT");
        return json(response, 200, marketMode === "bad-candles" ? { ...result, timeframe: "unknown" } : result);
      }
      return error(response, 404, "NOT_FOUND");
    }
    if (!session) return error(response, 401, "UNAUTHENTICATED");
    if (!accountRows.get(session.phone).totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    if (workspaceRead) {
      if (workspaceFixture) return json(response, ...workspaceFixture.handle(url, session.phone));
      if (url.pathname === "/api/v1/auto-trading/paper" && reportMode !== "empty") {
        return json(response, 200, { status: "ready", data: {
          source: "demo", environment: "PAPER", asOf: "2026-11-25T10:00:00Z", account: { equityPaise: 2506400 },
        } });
      }
      return json(response, 200, { status: "empty" });
    }
    if (request.headers.origin !== publicOrigin || csrfToken !== `ses.${sessionId}` || request.headers["x-csrf-token"] !== csrfToken) {
      return error(response, 403, "CSRF_FAILED");
    }
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    try {
      const body = JSON.parse(Buffer.concat(chunks).toString());
      if (workspaceFixture) return json(response, ...workspaceFixture.handle(url, session.phone, body));
      return json(response, 200, { received: body });
    } catch {
      return error(response, 400, "INVALID_REQUEST");
    }
  }

  if (url.pathname === "/api/v1/settings/profile") {
    if (!session) return error(response, 401, "UNAUTHENTICATED");
    const account = accountRows.get(session.phone);
    if (!account.totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    const writing = request.method === "PUT";
    const allowedCookies = writing ? [sessionName, csrfName] : [sessionName];
    if (Object.keys(cookies).some((name) => !allowedCookies.includes(name))) return error(response, 400, "UNEXPECTED_HEADERS");
    if (writing) {
      if (rejectNextProfileCsrf || request.headers.origin !== publicOrigin || csrfToken !== `ses.${sessionId}` || request.headers["x-csrf-token"] !== csrfToken) {
        rejectNextProfileCsrf = false;
        return error(response, 403, "CSRF_FAILED");
      }
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      let body;
      try {
        body = JSON.parse(Buffer.concat(chunks).toString());
      } catch {
        return error(response, 400, "INVALID_REQUEST");
      }
      if (typeof body.displayName !== "string" || !["Asia/Kolkata", "UTC"].includes(body.timezone)) return error(response, 400, "INVALID_REQUEST");
      account.displayName = body.displayName.trim();
      account.timezone = body.timezone;
    } else if (failNextProfileRead) {
      failNextProfileRead = false;
      return error(response, 503, "SETTINGS_UNAVAILABLE");
    }
    return json(response, 200, { displayName: account.displayName, timezone: account.timezone, phoneMasked: account.phoneMasked });
  }

  if (isAlertsFixtureRequest(url.pathname)) {
    if (!signedIn) return error(response, 401, "UNAUTHENTICATED");
    if (!accountRows.get(session.phone).totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    const writing = request.method === "POST" || request.method === "PUT";
    if (writing && (request.headers.origin !== publicOrigin || csrfToken !== `ses.${sessionId}` || request.headers["x-csrf-token"] !== csrfToken)) {
      return error(response, 403, "CSRF_FAILED");
    }
    const allowedCookies = writing ? [sessionName, csrfName] : [sessionName];
    if (Object.keys(cookies).some((name) => !allowedCookies.includes(name))) return error(response, 400, "UNEXPECTED_HEADERS");
    if (url.pathname === "/api/v1/alerts" && request.method === "GET") {
      const page = alerts.list(url.searchParams);
      return page ? json(response, 200, page) : error(response, 400, "INVALID_REQUEST");
    }
    if (url.pathname === "/api/v1/alerts/preferences") {
      if (request.method === "GET") return json(response, 200, alerts.preferences());
      if (request.method === "PUT") {
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        try {
          const prefs = alerts.save(JSON.parse(Buffer.concat(chunks).toString()));
          return prefs ? json(response, 200, prefs) : error(response, 400, "INVALID_REQUEST");
        } catch {
          return error(response, 400, "INVALID_REQUEST");
        }
      }
    }
    const id = /^\/api\/v1\/alerts\/([^/]+)\/ack$/.exec(url.pathname)?.[1];
    if (id && request.method === "POST") {
      const item = alerts.acknowledge(id);
      return item ? json(response, 200, item) : error(response, 404, "NOT_FOUND");
    }
    return error(response, 404, "NOT_FOUND");
  }

  if (request.method === "GET" && ["/api/v1/reports/paper", "/api/v1/reports/paper/trades.csv"].includes(url.pathname)) {
    if (!signedIn) return error(response, 401, "UNAUTHENTICATED");
    if (!accountRows.get(session.phone).totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    if (reportMode === "unavailable") return error(response, 503, "REPORTS_UNAVAILABLE");
    if (Object.keys(cookies).some((name) => name !== sessionName)) return error(response, 400, "UNEXPECTED_HEADERS");
    const period = { from: url.searchParams.get("from"), to: url.searchParams.get("to") };
    if (url.pathname.endsWith(".csv")) {
      response.writeHead(200, { "Content-Type": "text/csv; charset=utf-8" });
      return response.end(stagingReportCsv(period, reportMode));
    }
    return json(response, 200, reportMode === "empty" ? { status: "empty" } : stagingReport(period, reportMode));
  }

  if (Object.keys(cookies).some((name) => name !== sessionName && name !== csrfName) ||
      request.headers["x-tradeo-client-ip"] || request.headers["x-tradeo-ingress-token"] ||
      (endpoint !== "me" && (typeof clientIp !== "string" || !isIP(clientIp)))) {
    return error(response, 400, "UNEXPECTED_HEADERS");
  }

  if (endpoint === "me" && request.method === "GET") {
    if (sessionId === "upstream-offline") return error(response, 503, "AUTH_UNAVAILABLE");
    if (!signedIn) return error(response, 401, "UNAUTHENTICATED");
    return json(response, 200, sessionPayload(accountRows.get(session.phone), session));
  }
  if (endpoint === "csrf" && request.method === "GET") {
    const context = signedIn ? "session" : "pre_login";
    const token = signedIn ? `ses.${sessionId}` : csrfToken?.startsWith("pre.") ? csrfToken : `pre.${randomUUID()}`;
    const setCookies = [cookie(csrfName, token), "fixture-unrelated=ignored; Path=/"];
    if (sessionId && !signedIn) setCookies.unshift(`${cookie(sessionName, "")}; Max-Age=0`);
    return json(response, 200, { csrfToken: token, context, expiresAt: after(30) }, { "Set-Cookie": setCookies });
  }

  if (endpoint === "sessions" && request.method === "GET") {
    if (!session) return error(response, 401, "UNAUTHENTICATED");
    if (!accountRows.get(session.phone).totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    if (Object.keys(cookies).some((name) => name !== sessionName)) return error(response, 400, "UNEXPECTED_HEADERS");
    return json(response, 200, { sessions: Array.from(sessions.entries()).filter(([, row]) => row.phone === session.phone)
      .map(([id, row]) => ({ id, deviceLabel: row.deviceLabel, createdAt: row.createdAt, lastSeenAt: row.createdAt, expiresAt: after(180), current: id === sessionId })) });
  }
  if (endpoint?.startsWith("sessions/") && request.method === "DELETE") {
    if (!session) return error(response, 401, "UNAUTHENTICATED");
    if (!accountRows.get(session.phone).totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    if (request.headers.origin !== publicOrigin || csrfToken !== `ses.${sessionId}` || request.headers["x-csrf-token"] !== csrfToken) {
      return error(response, 403, "CSRF_FAILED");
    }
    if (!session.stepUpUntil || Date.parse(session.stepUpUntil) <= Date.now()) return error(response, 403, "STEP_UP_REQUIRED");
    const id = endpoint.slice(9);
    if (id === sessionId) return error(response, 409, "CURRENT_SESSION");
    if (sessions.get(id)?.phone !== session.phone) return error(response, 404, "SESSION_NOT_FOUND");
    sessions.delete(id);
    return response.writeHead(204).end();
  }

  if (request.method !== "POST" || !["otp/request", "otp/verify", "login/totp", "login/recovery", "totp/enroll", "totp/confirm", "totp/recovery-codes", "step-up", "logout"].includes(endpoint)) {
    return error(response, 404, "NOT_FOUND");
  }
  if (request.headers.origin !== publicOrigin || !csrfToken || request.headers["x-csrf-token"] !== csrfToken) {
    return error(response, 403, "CSRF_FAILED");
  }

  if (endpoint === "logout") {
    if (failNextLogout) {
      failNextLogout = false;
      return error(response, 503, "AUTH_UNAVAILABLE");
    }
    sessions.delete(sessionId);
    response.writeHead(204, { "Set-Cookie": [sessionName, csrfName].map((name) => `${cookie(name, "")}; Max-Age=0`) });
    return response.end();
  }

  if (endpoint.startsWith("totp/") || endpoint === "step-up") {
    if (!session) return error(response, 401, "UNAUTHENTICATED");
    if (csrfToken !== `ses.${sessionId}`) return error(response, 403, "CSRF_FAILED");
  }
  if (endpoint === "totp/enroll") {
    const account = accountRows.get(session.phone);
    if (account.totpEnabled) return error(response, 409, "TOTP_ALREADY_ENROLLED");
    account.pending = true;
    const secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    return json(response, 200, { secret, otpauthUri: `otpauth://totp/Tradeo:Fixture?secret=${secret}&issuer=Tradeo`, expiresAt: after(10) });
  }
  if (endpoint === "totp/recovery-codes") {
    const account = accountRows.get(session.phone);
    if (!account.totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    if (!session.stepUpUntil || Date.parse(session.stepUpUntil) <= Date.now()) return error(response, 403, "STEP_UP_REQUIRED");
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    if (chunks.length) return error(response, 400, "INVALID_REQUEST");
    account.recoveryCodes = newRecoveryCodes();
    return json(response, 200, { codes: account.recoveryCodes, createdAt: after(0) });
  }

  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  let body;
  try {
    body = JSON.parse(Buffer.concat(chunks).toString());
  } catch {
    return error(response, 422, "VALIDATION_ERROR");
  }

  if (endpoint === "step-up") {
    if (!accountRows.get(session.phone).totpEnabled) return error(response, 403, "TOTP_SETUP_REQUIRED");
    if (body.code !== "645721") return error(response, 422, "INVALID_TOTP");
    session.stepUpUntil = after(10);
    return json(response, 200, { totpEnabled: true, stepUpUntil: session.stepUpUntil });
  }

  if (endpoint === "otp/request") {
    if (body.phone === "+919876543211") return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    if (body.phone === "+919876543212") return error(response, 503, "OTP_DELIVERY_UNAVAILABLE");
    if (!/^\+91987654321[034589]$/.test(body.phone)) return error(response, 422, "VALIDATION_ERROR");
    const channel = body.channel ?? "sms";
    if (body.phone === registrationNumber && channel !== "email") return error(response, 400, "INVALID_REQUEST");
    const requests = otpRequestsByIp.get(clientIp) ?? 0;
    if (requests >= 2) return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    otpRequestsByIp.set(clientIp, requests + 1);
    const challengeId = randomUUID();
    challenges.set(challengeId, { csrfToken, phone: body.phone });
    return json(response, 202, { challengeId, channel, expiresAt: after(5), resendAvailableAt: after(0) });
  }

  if (endpoint === "otp/verify") {
    const challenge = challenges.get(body.challengeId);
    const account = challenge ? accountRows.get(challenge.phone) : undefined;
    if (!account || account.totpEnabled || challenge.csrfToken !== csrfToken || body.code !== "842615") return error(response, 401, "INVALID_OTP");
    challenges.delete(body.challengeId);
    return startSession(response, challenge.phone, sessionId, false);
  }
  if (endpoint === "totp/confirm") {
    const account = accountRows.get(session.phone);
    if (!account.pending) return error(response, 409, "TOTP_NOT_PENDING");
    if (body.code !== "615408") return error(response, 422, "INVALID_TOTP");
    account.pending = false;
    account.totpEnabled = true;
    account.lastCode = body.code;
    session.stepUpUntil = after(10);
    return json(response, 200, { totpEnabled: true, stepUpUntil: session.stepUpUntil });
  }
  if (body.phone === "+919876543211") return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
  const account = accountRows.get(body.phone);
  if (endpoint === "login/recovery") {
    if (Object.keys(body).length !== 2 || !csrfToken.startsWith("pre.") || !account?.totpEnabled || !account.recoveryCodes.includes(body.recoveryCode)) {
      return error(response, 401, "INVALID_CREDENTIALS");
    }
    account.totpEnabled = false;
    account.lastCode = null;
    account.recoveryCodes = [];
    for (const active of sessions.values()) {
      if (active.phone === body.phone) active.stepUpUntil = null;
    }
    return startSession(response, body.phone, sessionId, false);
  }
  const valid = body.phone === returningNumber ? body.code === "728391" : ["615408", "615409"].includes(body.code);
  if (!csrfToken.startsWith("pre.") || !account?.totpEnabled || !valid || body.code === account.lastCode) {
    return error(response, 401, "INVALID_CREDENTIALS");
  }
  account.lastCode = body.code;
  return startSession(response, body.phone, sessionId, true);
}).listen(3102, "127.0.0.1");
