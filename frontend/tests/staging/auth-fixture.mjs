import { randomUUID } from "node:crypto";
import { createServer, request as httpRequest } from "node:http";
import { isIP } from "node:net";

const publicOrigin = "http://127.0.0.1:3101";
const sessionName = "__Host-tradeo_session";
const csrfName = "__Host-tradeo_csrf";
const cookieAttrs = "Secure; HttpOnly; SameSite=Lax; Path=/";
const sessionIds = new Set();
const challenges = new Map();
const otpRequestsByIp = new Map();
const user = { id: randomUUID(), phoneMasked: "+91******3210", displayName: null, createdAt: "2026-11-25T00:00:00Z" };
const sessionDates = { idleExpiresAt: "2026-11-25T01:00:00Z", expiresAt: "2026-11-25T12:00:00Z" };
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

createServer(async (request, response) => {
  if (request.url === "/health") return json(response, 200, { ok: true });

  const endpoint = request.url?.replace(/^\/api\/v1\/auth\//, "");
  const cookies = Object.fromEntries((request.headers.cookie ?? "").split("; ").filter(Boolean).map((item) => item.split("=", 2)));
  const sessionId = cookies[sessionName];
  const signedIn = sessionIds.has(sessionId);
  const csrfToken = cookies[csrfName];
  const clientIp = request.headers["x-forwarded-for"];

  if (Object.keys(cookies).some((name) => name !== sessionName && name !== csrfName) ||
      request.headers["x-tradeo-client-ip"] || request.headers["x-tradeo-ingress-token"] ||
      (endpoint !== "me" && (typeof clientIp !== "string" || !isIP(clientIp)))) {
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
    if (!/^\+91987654321[0345]$/.test(body.phone)) return error(response, 422, "VALIDATION_ERROR");
    const requests = otpRequestsByIp.get(clientIp) ?? 0;
    if (requests >= 2) return error(response, 429, "RATE_LIMITED", { "Retry-After": "30" });
    otpRequestsByIp.set(clientIp, requests + 1);
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
