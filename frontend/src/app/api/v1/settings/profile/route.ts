import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";
import { authCookieHeader, sessionCookie } from "@/lib/auth/upstream";

const responseHeaders = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

function fail(status: number, code: string, message: string) {
  return Response.json({ code, message }, { status, headers: responseHeaders });
}

async function proxy(request: NextRequest) {
  const config = readAuthConfig();
  if (config.mode === "preview") return fail(404, "NOT_FOUND", "Account settings are unavailable in preview.");
  if (config.mode === "unavailable") return fail(503, "SETTINGS_UNAVAILABLE", "Account settings are temporarily unavailable.");
  const clientIp = getTrustedClientIp(request.headers, config.ingressToken);
  if (!clientIp) return fail(403, "UNTRUSTED_INGRESS", "Account settings require the staging ingress.");
  if (!request.cookies.get(sessionCookie)?.value) return fail(401, "UNAUTHENTICATED", "Sign in to continue.");
  const saving = request.method === "PUT";
  const cookie = authCookieHeader((name) => saving || name === sessionCookie ? request.cookies.get(name)?.value : undefined);
  const headers = new Headers({ Accept: "application/json", "X-Forwarded-For": clientIp, Cookie: cookie });

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
    const outputHeaders = new Headers({ ...responseHeaders, "Content-Type": "application/json" });
    const retryAfter = response.headers.get("retry-after");
    if (retryAfter) outputHeaders.set("Retry-After", retryAfter);
    return new Response(response.body, { status: response.status, headers: outputHeaders });
  } catch {
    return fail(503, "SETTINGS_UNAVAILABLE", "Account settings are temporarily unavailable.");
  }
}

export { proxy as GET, proxy as PUT };
