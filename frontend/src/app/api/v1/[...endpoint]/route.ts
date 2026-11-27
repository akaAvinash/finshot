import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { apiProxyResponse } from "@/lib/api/proxy-response";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";
import { authCookieHeader, sessionCookie } from "@/lib/auth/upstream";

type Endpoint = {
  methods: readonly ("GET" | "POST" | "PUT")[];
  account: boolean;
  queryKeys?: readonly string[];
};

const endpoints = new Map<string, Endpoint>([
  ["market/instruments", { methods: ["GET"], account: false, queryKeys: ["query"] }],
  ["market/overview", { methods: ["GET"], account: false }],
  ["brokers/preview", { methods: ["GET"], account: true }],
  ["broker-connections", { methods: ["GET"], account: true }],
  ["broker-connections/authorizations", { methods: ["POST"], account: true }],
  ["broker-connections/authorizations/callback", { methods: ["POST"], account: true }],
  ["settings/trade-controls", { methods: ["GET", "PUT"], account: true }],
  ["settings/trade-controls/history", { methods: ["GET"], account: true }],
  ["strategies/preview", { methods: ["GET"], account: true }],
  ["strategies/preview/commands", { methods: ["POST"], account: true }],
  ["backtests/preview", { methods: ["GET"], account: true }],
  ["backtests/preview/runs", { methods: ["POST"], account: true }],
  ["auto-trading/paper", { methods: ["GET"], account: true }],
  ["auto-trading/paper/commands", { methods: ["POST"], account: true }],
  ["reports/paper", { methods: ["GET"], account: true, queryKeys: ["from", "to"] }],
  ["agents", { methods: ["GET"], account: true }],
  ["agents/health", { methods: ["GET"], account: true }],
  ["agents/events", { methods: ["GET"], account: true, queryKeys: ["agentId", "cursor", "limit"] }],
]);

const jsonMediaType = /^application\/json(?:\s*;|$)/i;
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const maxBodyBytes = 16 * 1024;
const maxQueryLength = 2048;

function matchEndpoint(segments: string[]): { path: string; endpoint: Endpoint } | undefined {
  const [area, collection, id, action] = segments;
  if (segments.length === 4 && area === "market" && collection === "instruments" && action === "candles" &&
      /^NSE:[A-Z0-9_.&-]+$/.test(id)) {
    return { path: `market/instruments/${encodeURIComponent(id)}/candles`, endpoint: { methods: ["GET"], account: false, queryKeys: ["timeframe"] } };
  }
  if (segments.length === 4 && area === "brokers" && collection === "preview" && action === "actions" &&
      (id === "zerodha" || id === "fyers")) {
    return { path: `brokers/preview/${id}/actions`, endpoint: { methods: ["POST"], account: true } };
  }
  if (segments.length === 4 && area === "backtests" && collection === "preview" && id === "runs" && uuid.test(action)) {
    return { path: `backtests/preview/runs/${action}`, endpoint: { methods: ["GET"], account: true } };
  }
  if (segments.length === 3 && area === "broker-connections" && uuid.test(collection) && (id === "actions" || id === "portfolio")) {
    return { path: `broker-connections/${collection}/${id}`, endpoint: { methods: [id === "actions" ? "POST" : "GET"], account: true } };
  }
  if (segments.some((segment) => segment.includes("/"))) return undefined;
  const path = segments.join("/");
  const endpoint = endpoints.get(path);
  if (endpoint) return { path, endpoint };
}

type Context = { params: Promise<{ endpoint: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const { fail, requestId, wrongMethod, relay } = apiProxyResponse(request);
  const config = readAuthConfig();
  const match = matchEndpoint((await context.params).endpoint);
  if (!match || config.mode === "preview") return fail(404, "NOT_FOUND", "API endpoint unavailable.");
  const { path, endpoint } = match;
  if (!endpoint.methods.some((method) => request.method === method)) return wrongMethod(endpoint.methods);
  if (config.mode === "unavailable") return fail(503, "API_UNAVAILABLE", "The staging API is temporarily unavailable.");

  const clientIp = getTrustedClientIp(request.headers, config.ingressToken);
  if (!clientIp) return fail(403, "UNTRUSTED_INGRESS", "Use the staging address to access the API.");
  if (endpoint.account && !request.cookies.get(sessionCookie)?.value) return fail(401, "UNAUTHENTICATED", "Sign in to continue.");

  const { search, searchParams } = request.nextUrl;
  if (search.length > maxQueryLength || [...searchParams.keys()].some((key) => !endpoint.queryKeys?.includes(key))) {
    return fail(400, "INVALID_REQUEST", "Unsupported API query parameters.");
  }

  const writing = request.method !== "GET";
  const headers = new Headers({ Accept: "application/json", "X-Forwarded-For": clientIp, "X-Request-ID": requestId });
  if (endpoint.account) {
    headers.set("Cookie", authCookieHeader((name) => writing || name === sessionCookie ? request.cookies.get(name)?.value : undefined));
  }

  try {
    let body: string | undefined;
    if (writing) {
      const origin = request.headers.get("origin");
      const csrf = request.headers.get("x-csrf-token");
      if (origin !== config.publicOrigin || !csrf) return fail(403, "CSRF_FAILED", "The request could not be verified.");
      if (!jsonMediaType.test(request.headers.get("content-type") ?? "")) {
        return fail(415, "UNSUPPORTED_MEDIA_TYPE", "Send an application/json request.");
      }
      const payload = await readBoundedBody(request, maxBodyBytes);
      if (payload === null) return fail(413, "PAYLOAD_TOO_LARGE", "The request is too large.");
      headers.set("Origin", origin);
      headers.set("X-CSRF-Token", csrf);
      headers.set("Content-Type", "application/json");
      body = payload;
    }

    const upstream = await fetch(`${config.upstream}/api/v1/${path}${search}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
    });
    const contentType = upstream.headers.get("content-type") ?? "";
    if (!jsonMediaType.test(contentType)) {
      await upstream.body?.cancel();
      return fail(502, "API_UNAVAILABLE", "The staging API returned an unexpected response.");
    }
    return await relay(upstream);
  } catch {
    return fail(503, "API_UNAVAILABLE", "The staging API is temporarily unavailable.");
  }
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
