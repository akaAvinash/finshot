import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { apiProxyResponse } from "@/lib/api/proxy-response";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";
import { authCookieHeader, authEndpointMethod, authResponseCookies, getAuthEndpoint, requestUpstreamAuth, sessionCookie } from "@/lib/auth/upstream";

const maxBodyBytes = 1024;

type Context = { params: Promise<{ endpoint: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const { fail: errorResponse, requestId, wrongMethod, relay } = apiProxyResponse(request, "no-store");
  const config = readAuthConfig();
  const endpoint = getAuthEndpoint((await context.params).endpoint.join("/"));
  if (!endpoint || config.mode === "preview") return errorResponse(404, "NOT_FOUND", "Auth endpoint unavailable.");
  if (endpoint === "login/tester" && (config.mode !== "staging" || !config.testerSignInEnabled)) {
    return errorResponse(404, "NOT_FOUND", "Auth endpoint unavailable.");
  }
  const method = authEndpointMethod(endpoint);
  if (request.method !== method) return wrongMethod([method]);
  if (config.mode === "unavailable") return errorResponse(503, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable.");

  const clientIp = getTrustedClientIp(request.headers, config.ingressToken);
  if (!clientIp) return errorResponse(403, "UNTRUSTED_INGRESS", "Sign-in must go through the staging ingress.");

  const headers = new Headers({ Accept: "application/json", "X-Forwarded-For": clientIp, "X-Request-ID": requestId });
  const cookie = authCookieHeader((name) => endpoint !== "sessions" || name === sessionCookie ? request.cookies.get(name)?.value : undefined);
  if (cookie) headers.set("Cookie", cookie);
  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers.set("User-Agent", userAgent);

  try {
    let body: string | undefined;
    if (method !== "GET") {
      const origin = request.headers.get("origin");
      const csrfToken = request.headers.get("x-csrf-token");
      if (origin !== config.publicOrigin || !csrfToken) {
        return errorResponse(403, "CSRF_FAILED", "The request could not be verified. Reload and try again.");
      }
      headers.set("Origin", origin);
      headers.set("X-CSRF-Token", csrfToken);
      const acceptsBody = method === "POST" && endpoint !== "logout" && endpoint !== "totp/enroll" && endpoint !== "totp/recovery-codes";
      if (acceptsBody && !/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")) {
        return errorResponse(415, "UNSUPPORTED_MEDIA_TYPE", "Send a JSON request.");
      }
      const payload = await readBoundedBody(request, maxBodyBytes);
      if (payload === null) return errorResponse(413, "PAYLOAD_TOO_LARGE", "The request is too large.");
      if (acceptsBody) {
        headers.set("Content-Type", "application/json");
        body = payload;
      } else if (payload) return errorResponse(400, "INVALID_REQUEST", "This request does not accept a body.");
    }

    const upstream = await requestUpstreamAuth(config.upstream, endpoint, { headers, body });
    if (upstream.status !== 204 && !/^application\/json(?:\s*;|$)/i.test(upstream.headers.get("content-type") ?? "")) {
      await upstream.body?.cancel();
      return errorResponse(502, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable.");
    }
    return await relay(upstream, authResponseCookies(upstream));
  } catch {
    return errorResponse(503, "AUTH_UNAVAILABLE", "Sign-in is temporarily unavailable.");
  }
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
