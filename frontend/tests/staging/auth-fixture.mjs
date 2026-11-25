import { randomUUID } from "node:crypto";
import { createServer, request as httpRequest } from "node:http";
import { isIP } from "node:net";
import { stagingReport, stagingReportCsv } from "./paper-report-fixture.mjs";
import { createAlertsFixture, isAlertsFixtureRequest } from "./alerts-fixture.mjs";

const publicOrigin = "http://127.0.0.1:3101";
const sessionName = "__Host-tradeo_session";
const csrfName = "__Host-tradeo_csrf";
const cookieAttrs = "Secure; HttpOnly; SameSite=Lax; Path=/";
const sessions = new Map();
const challenges = new Map();
const otpRequestsByIp = new Map();
let failNextLogout = false;
let reportMode = "ready";
let alerts = createAlertsFixture();
const returningEmail = "owner@example.com";
const registrationEmail = "new@example.com";
const accountRows = new Map();
const after = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();
const recoveryCodes = (prefix) => [..."abcdefghij"].map((letter) => `${prefix}${letter}-abcde`);

function resetAccounts() {
  accountRows.clear();
  for (const email of [returningEmail, registrationEmail]) {
    accountRows.set(email, { id: randomUUID(), emailMasked: `${email[0]}***@example.com`, displayName: null,
      createdAt: after(0), totpEnabled: email === returningEmail, pending: false, lastCode: null,
      recoveryCodes: email === returningEmail ? ["abcde-fghij"] : [] });
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
  const { id, emailMasked, displayName, createdAt, totpEnabled } = account;
  return { user: { id, emailMasked, displayName, createdAt, totpEnabled },
    session: { idleExpiresAt: after(30), expiresAt: after(180), stepUpUntil: session.stepUpUntil } };
}

function startSession(response, email, previousId, steppedUp) {
  sessions.delete(previousId);
  const id = randomUUID();
  const session = { email, stepUpUntil: steppedUp ? after(10) : null };
  sessions.set(id, session);
  const token = `ses.${id}`;
  return json(response, 200, { ...sessionPayload(accountRows.get(email), session), csrfToken: token }, {
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
    reportMode = "ready";
    alerts = createAlertsFixture();
    return response.writeHead(204).end();
  }
  if (request.method === "POST" && request.url === "/__fixture/fail-next-logout") {
    failNextLogout = true;
    return response.writeHead(204).end();
  }

  const url = new URL(request.url, publicOrigin);
  if (request.method === "POST" && /^\/__fixture\/report\/(ready|empty|unavailable|mismatch|large)$/.test(url.pathname)) {
    reportMode = url.pathname.split("/").at(-1);
    return response.writeHead(204).end();
  }

  const endpoint = request.url?.replace(/^\/api\/v1\/auth\//, "");
  const cookies = Object.fromEntries((request.headers.cookie ?? "").split("; ").filter(Boolean).map((item) => item.split("=", 2)));
  const sessionId = cookies[sessionName];
  const session = sessions.get(sessionId);
  const signedIn = Boolean(session);
  const csrfToken = cookies[csrfName];
  const clientIp = request.headers["x-forwarded-for"];

  if (isAlertsFixtureRequest(url.pathname)) {
    if (!signedIn) return error(response, 401, "UNAUTHENTICATED");
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
    return json(response, 200, sessionPayload(accountRows.get(session.email), session));
  }
  if (endpoint === "csrf" && request.method === "GET") {
    const context = signedIn ? "session" : "pre_login";
    const token = signedIn ? `ses.${sessionId}` : csrfToken?.startsWith("pre.") ? csrfToken : `pre.${randomUUID()}`;
    const setCookies = [cookie(csrfName, token), "fixture-unrelated=ignored; Path=/"];
    if (sessionId && !signedIn) setCookies.unshift(`${cookie(sessionName, "")}; Max-Age=0`);
    return json(response, 200, { csrfToken: token, context, expiresAt: after(30) }, { "Set-Cookie": setCookies });
  }

  if (request.method !== "POST" || !["otp/request", "otp/verify", "totp/enroll", "totp/confirm", "logout"].includes(endpoint)) {
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

  if (endpoint === "totp/enroll" || endpoint === "totp/confirm") {
    if (!session) return error(response, 401, "UNAUTHENTICATED");
    if (csrfToken !== `ses.${sessionId}`) return error(response, 403, "CSRF_FAILED");
  }
  if (endpoint === "totp/enroll") {
    const account = accountRows.get(session.email);
    if (account.totpEnabled) return error(response, 409, "TOTP_ALREADY_ENROLLED");
    account.pending = true;
    const secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    return json(response, 200, { secret, otpauthUri: `otpauth://totp/Tradeo:Fixture?secret=${secret}&issuer=Tradeo`, expiresAt: after(10) });
  }

  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  let body;
  try {
    body = JSON.parse(Buffer.concat(chunks).toString());
  } catch {
    return error(response, 422, "VALIDATION_ERROR");
  }

  if (endpoint === "otp/request") {
    if (Object.keys(body).length !== 1 || !/^[a-z-]+@example\.com$/.test(body.email)) return error(response, 422, "VALIDATION_ERROR");
    if (body.email === "limited@example.com") return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    if (body.email === "down@example.com") return error(response, 503, "OTP_DELIVERY_UNAVAILABLE");
    const requests = otpRequestsByIp.get(clientIp) ?? 0;
    if (clientIp === fixtureAddresses.get("limited") && requests >= 2) return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    otpRequestsByIp.set(clientIp, requests + 1);
    const challengeId = randomUUID();
    const method = accountRows.get(body.email)?.totpEnabled ? "totp" : "email";
    challenges.set(challengeId, { csrfToken, email: body.email, method });
    return json(response, 202, { challengeId, expiresAt: after(5), resendAvailableAt: after(0) });
  }

  if (endpoint === "otp/verify") {
    if (Object.keys(body).length !== 2 || (typeof body.code === "string") === (typeof body.recoveryCode === "string")) {
      return error(response, 422, "VALIDATION_ERROR");
    }
    const challenge = challenges.get(body.challengeId);
    if (!challenge || challenge.csrfToken !== csrfToken) return error(response, 401, "INVALID_OTP");
    if (challenge.email === "verify-limited@example.com") return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    const account = accountRows.get(challenge.email);
    if (!account || account.totpEnabled !== (challenge.method === "totp")) return error(response, 401, "INVALID_OTP");
    const usingRecovery = typeof body.recoveryCode === "string";
    if (usingRecovery) {
      const trimmed = body.recoveryCode.toLowerCase().replace("-", "");
      if (!account.totpEnabled || !account.recoveryCodes.some((value) => value.replace("-", "") === trimmed)) {
        return error(response, 401, "INVALID_OTP");
      }
      account.totpEnabled = false;
      account.recoveryCodes = [];
    } else {
      const valid = account.totpEnabled ? ["728391", "615408", "615409"].includes(body.code) : body.code === "842615";
      if (!valid || body.code === account.lastCode) return error(response, 401, "INVALID_OTP");
      account.lastCode = body.code;
    }
    challenges.delete(body.challengeId);
    return startSession(response, challenge.email, sessionId, account.totpEnabled);
  }
  if (endpoint === "totp/confirm") {
    const account = accountRows.get(session.email);
    if (!account.pending) return error(response, 409, "TOTP_NOT_PENDING");
    if (body.code !== "615408") return error(response, 422, "INVALID_TOTP");
    account.pending = false;
    account.totpEnabled = true;
    account.lastCode = body.code;
    account.recoveryCodes = recoveryCodes(session.email === returningEmail ? "zzzz" : "yyyy");
    session.stepUpUntil = after(10);
    return json(response, 200, { totpEnabled: true, stepUpUntil: session.stepUpUntil, recoveryCodes: account.recoveryCodes });
  }
}).listen(3102, "127.0.0.1");
