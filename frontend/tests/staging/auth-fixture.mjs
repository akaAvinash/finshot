import { randomUUID } from "node:crypto";
import { createServer } from "node:http";

const publicOrigin = "http://127.0.0.1:3101";
const sessionName = "__Host-tradeo_session";
const csrfName = "__Host-tradeo_csrf";
const cookieAttrs = "Secure; HttpOnly; SameSite=Lax; Path=/";
const sessionIds = new Set();
const challenges = new Map();
const user = { id: randomUUID(), phoneMasked: "+91******3210", displayName: null, createdAt: "2026-11-25T00:00:00Z" };
const sessionDates = { idleExpiresAt: "2026-11-25T01:00:00Z", expiresAt: "2026-11-25T12:00:00Z" };

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

createServer(async (request, response) => {
  if (request.url === "/health") return json(response, 200, { ok: true });

  const endpoint = request.url?.replace(/^\/api\/v1\/auth\//, "");
  const cookies = Object.fromEntries((request.headers.cookie ?? "").split("; ").filter(Boolean).map((item) => item.split("=", 2)));
  const sessionId = cookies[sessionName];
  const signedIn = sessionIds.has(sessionId);
  const csrfToken = cookies[csrfName];

  if (Object.keys(cookies).some((name) => name !== sessionName && name !== csrfName) || request.headers["x-forwarded-for"]) {
    return error(response, 400, "UNEXPECTED_HEADERS");
  }

  if (endpoint === "me" && request.method === "GET") {
    if (sessionId === "upstream-offline") return error(response, 503, "AUTH_UNAVAILABLE");
    if (!signedIn) return error(response, 401, "UNAUTHENTICATED");
    return json(response, 200, { user, session: sessionDates });
  }
  if (endpoint === "csrf" && request.method === "GET") {
    const context = signedIn ? "session" : "pre_login";
    const token = signedIn ? `ses.${sessionId}` : csrfToken?.startsWith("pre.") ? csrfToken : `pre.${randomUUID()}`;
    const setCookies = [cookie(csrfName, token), "fixture-unrelated=ignored; Path=/"];
    if (sessionId && !signedIn) setCookies.unshift(`${cookie(sessionName, "")}; Max-Age=0`);
    return json(response, 200, { csrfToken: token, context, expiresAt: sessionDates.expiresAt }, { "Set-Cookie": setCookies });
  }

  if (request.method !== "POST" || !["otp/request", "otp/verify", "logout"].includes(endpoint)) {
    return error(response, 404, "NOT_FOUND");
  }
  if (request.headers.origin !== publicOrigin || !csrfToken || request.headers["x-csrf-token"] !== csrfToken) {
    return error(response, 403, "CSRF_FAILED");
  }

  if (endpoint === "logout") {
    sessionIds.delete(sessionId);
    response.writeHead(204, { "Set-Cookie": [sessionName, csrfName].map((name) => `${cookie(name, "")}; Max-Age=0`) });
    return response.end();
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
    if (body.phone === "+919876543211") return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    if (body.phone === "+919876543212") return error(response, 503, "OTP_DELIVERY_UNAVAILABLE");
    if (body.phone !== "+919876543210") return error(response, 422, "VALIDATION_ERROR");
    const challengeId = randomUUID();
    challenges.set(challengeId, csrfToken);
    return json(response, 202, { challengeId, expiresAt: sessionDates.idleExpiresAt, resendAvailableAt: sessionDates.idleExpiresAt });
  }

  if (challenges.get(body.challengeId) !== csrfToken || body.code !== "842615") {
    return error(response, 401, "INVALID_OTP");
  }
  challenges.delete(body.challengeId);
  const newSessionId = randomUUID();
  sessionIds.add(newSessionId);
  const token = `ses.${newSessionId}`;
  return json(response, 200, { user, session: sessionDates, csrfToken: token }, {
    "Set-Cookie": [cookie(sessionName, newSessionId), cookie(csrfName, token)],
  });
}).listen(3102, "127.0.0.1");
