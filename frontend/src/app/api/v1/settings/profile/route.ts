import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { apiProxyResponse } from "@/lib/api/proxy-response";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";
import { authCookieHeader, sessionCookie } from "@/lib/auth/upstream";

async function proxy(request: NextRequest) {
  const { fail, requestId, wrongMethod, relay } = apiProxyResponse(request);
  const config = readAuthConfig();
  if (config.mode === "preview") return fail(404, "NOT_FOUND", "Account settings are unavailable in preview.");
  if (request.method !== "GET" && request.method !== "PUT") return wrongMethod(["GET", "PUT"]);
  if (config.mode === "unavailable") return fail(503, "SETTINGS_UNAVAILABLE", "Account settings are temporarily unavailable.");
  const clientIp = getTrustedClientIp(request.headers, config.ingressToken);
  if (!clientIp) return fail(403, "UNTRUSTED_INGRESS", "Account settings require the staging ingress.");
  if (!request.cookies.get(sessionCookie)?.value) return fail(401, "UNAUTHENTICATED", "Sign in to continue.");
  const saving = request.method === "PUT";
  const cookie = authCookieHeader((name) => saving || name === sessionCookie ? request.cookies.get(name)?.value : undefined);
  const headers = new Headers({ Accept: "application/json", "X-Forwarded-For": clientIp, "X-Request-ID": requestId, Cookie: cookie });

  try {
    let body: string | undefined;
    if (saving) {
      const origin = request.headers.get("origin");
      const csrf = request.headers.get("x-csrf-token");
      if (origin !== config.publicOrigin || !csrf) return fail(403, "CSRF_FAILED", "This request could not be verified.");
      if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")) return fail(415, "UNSUPPORTED_MEDIA_TYPE", "Send the profile as JSON.");
      const payload = await readBoundedBody(request, 1024);
      if (payload === null) return fail(413, "PAYLOAD_TOO_LARGE", "The profile request is too large.");
      headers.set("Origin", origin);
      headers.set("X-CSRF-Token", csrf);
      headers.set("Content-Type", "application/json");
      body = payload;
    }
    const response = await fetch(`${config.upstream}/api/v1/settings/profile`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
    });
    if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) {
      await response.body?.cancel();
      return fail(502, "SETTINGS_UNAVAILABLE", "Account settings are temporarily unavailable.");
    }
    return await relay(response);
  } catch {
    return fail(503, "SETTINGS_UNAVAILABLE", "Account settings are temporarily unavailable.");
  }
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
