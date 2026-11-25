import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";
import { authCookieHeader, authEndpoints, authProxyResponse, getAuthEndpoint, requestUpstreamAuth } from "@/lib/auth/upstream";

const maxBodyBytes = 1024;

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ code, message }, { status, headers: { "Cache-Control": "no-store" } });
}

type Context = { params: Promise<{ endpoint: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const config = readAuthConfig();
  const endpoint = getAuthEndpoint((await context.params).endpoint.join("/"));
  if (!endpoint || config.mode === "preview") return errorResponse(404, "NOT_FOUND", "Auth endpoint unavailable.");
  if (request.method !== authEndpoints[endpoint]) {
    return new Response(null, { status: 405, headers: { Allow: authEndpoints[endpoint], "Cache-Control": "no-store" } });
  }
  if (config.mode === "unavailable") return errorResponse(503, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable.");

  const clientIp = getTrustedClientIp(request.headers, config.ingressToken);
  if (!clientIp) return errorResponse(403, "UNTRUSTED_INGRESS", "Sign-in must go through the staging ingress.");

  const headers = new Headers({ Accept: "application/json", "X-Forwarded-For": clientIp });
  const cookie = authCookieHeader((name) => request.cookies.get(name)?.value);
  if (cookie) headers.set("Cookie", cookie);
  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers.set("User-Agent", userAgent);

  try {
    let body: string | undefined;
    if (request.method === "POST") {
      const origin = request.headers.get("origin");
      const csrfToken = request.headers.get("x-csrf-token");
      if (origin !== config.publicOrigin || !csrfToken) {
        return errorResponse(403, "CSRF_FAILED", "The request could not be verified. Reload and try again.");
      }
      headers.set("Origin", origin);
      headers.set("X-CSRF-Token", csrfToken);
      if (endpoint !== "logout" && !/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")) {
        return errorResponse(415, "UNSUPPORTED_MEDIA_TYPE", "Send a JSON request.");
      }
      const payload = await readBoundedBody(request, maxBodyBytes);
      if (payload === null) return errorResponse(413, "PAYLOAD_TOO_LARGE", "The request is too large.");
      if (endpoint !== "logout") {
        headers.set("Content-Type", "application/json");
        body = payload;
      }
    }

    const upstream = await requestUpstreamAuth(config.upstream, endpoint, { headers, body });
    if (upstream.status !== 204 && !/^application\/json(?:\s*;|$)/i.test(upstream.headers.get("content-type") ?? "")) {
      return errorResponse(502, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable.");
    }
    return authProxyResponse(upstream);
  } catch {
    return errorResponse(503, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable.");
  }
}

export { proxy as GET, proxy as POST };
