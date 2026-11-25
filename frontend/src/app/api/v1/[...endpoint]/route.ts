import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";
import { authCookieHeader, sessionCookie } from "@/lib/auth/upstream";

type Endpoint = {
  method: "GET" | "POST";
  account: boolean;
  queryKeys?: readonly string[];
};

const endpoints = new Map<string, Endpoint>([
  ["market/instruments", { method: "GET", account: false, queryKeys: ["query"] }],
  ["market/overview", { method: "GET", account: false }],
  ["brokers/preview", { method: "GET", account: true }],
  ["strategies/preview", { method: "GET", account: true }],
  ["strategies/preview/commands", { method: "POST", account: true }],
  ["auto-trading/paper", { method: "GET", account: true }],
  ["auto-trading/paper/commands", { method: "POST", account: true }],
  ["reports/paper", { method: "GET", account: true, queryKeys: ["from", "to"] }],
]);

const responseHeaders = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const jsonMediaType = /^application\/json(?:\s*;|$)/i;
const maxBodyBytes = 16 * 1024;
const maxQueryLength = 2048;

function matchEndpoint(segments: string[]): { path: string; endpoint: Endpoint } | undefined {
  const [area, collection, id, action] = segments;
  if (segments.length === 4 && area === "market" && collection === "instruments" && action === "candles" &&
      /^NSE:[A-Z0-9_.&-]+$/.test(id)) {
    return { path: `market/instruments/${encodeURIComponent(id)}/candles`, endpoint: { method: "GET", account: false, queryKeys: ["timeframe"] } };
  }
  if (segments.length === 4 && area === "brokers" && collection === "preview" && action === "actions" &&
      (id === "zerodha" || id === "fyers")) {
    return { path: `brokers/preview/${id}/actions`, endpoint: { method: "POST", account: true } };
  }
  if (segments.some((segment) => segment.includes("/"))) return undefined;
  const path = segments.join("/");
  const endpoint = endpoints.get(path);
  if (endpoint) return { path, endpoint };
}

function fail(status: number, code: string, message: string) {
  return Response.json({ code, message }, { status, headers: responseHeaders });
}

type Context = { params: Promise<{ endpoint: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const config = readAuthConfig();
  const match = matchEndpoint((await context.params).endpoint);
  if (!match || config.mode === "preview") return fail(404, "NOT_FOUND", "API endpoint unavailable.");
  const { path, endpoint } = match;
  if (request.method !== endpoint.method) {
    return new Response(null, { status: 405, headers: { ...responseHeaders, Allow: endpoint.method } });
  }
  if (config.mode === "unavailable") return fail(503, "API_UNAVAILABLE", "The staging API is temporarily unavailable.");

  const clientIp = getTrustedClientIp(request.headers, config.ingressToken);
  if (!clientIp) return fail(403, "UNTRUSTED_INGRESS", "Use the staging address to access the API.");
  if (endpoint.account && !request.cookies.get(sessionCookie)?.value) return fail(401, "UNAUTHENTICATED", "Sign in to continue.");

  const { search, searchParams } = request.nextUrl;
  if (search.length > maxQueryLength || [...searchParams.keys()].some((key) => !endpoint.queryKeys?.includes(key))) {
    return fail(400, "INVALID_REQUEST", "Unsupported API query parameters.");
  }

  const writing = endpoint.method === "POST";
  const headers = new Headers({ Accept: "application/json", "X-Forwarded-For": clientIp });
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
      method: endpoint.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
    });
    const contentType = upstream.headers.get("content-type") ?? "";
    if (!jsonMediaType.test(contentType)) {
      await upstream.body?.cancel();
      return fail(502, "API_UNAVAILABLE", "The staging API returned an unexpected response.");
    }
    const outputHeaders = new Headers({ ...responseHeaders, "Content-Type": contentType });
    for (const name of ["retry-after", "x-request-id"]) {
      const value = upstream.headers.get(name);
      if (value) outputHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: outputHeaders });
  } catch {
    return fail(503, "API_UNAVAILABLE", "The staging API is temporarily unavailable.");
  }
}

export { proxy as GET, proxy as POST };
