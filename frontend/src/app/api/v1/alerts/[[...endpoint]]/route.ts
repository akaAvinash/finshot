import type { NextRequest } from "next/server";
import { readBoundedBody } from "@/lib/api/bounded-body";
import { readAuthConfig } from "@/lib/auth/config";
import { authCookieHeader, sessionCookie } from "@/lib/auth/upstream";

const privateHeaders = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const filterKeys = new Set(["status", "severity", "source", "cursor", "limit"]);

function fail(status: number, code: string, message: string) {
  return Response.json({ code, message }, { status, headers: privateHeaders });
}

type Context = { params: Promise<{ endpoint?: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const config = readAuthConfig();
  if (config.mode === "preview") return fail(404, "NOT_FOUND", "Alerts API is unavailable in preview mode.");
  if (config.mode === "unavailable") return fail(503, "ALERTS_UNAVAILABLE", "Alerts are temporarily unavailable.");
  if (!request.cookies.get(sessionCookie)?.value) return fail(401, "UNAUTHENTICATED", "Sign in to continue.");

  const segments = (await context.params).endpoint ?? [];
  let path: string;
  let methods: string[];
  if (segments.length === 0) {
    path = "/api/v1/alerts";
    methods = ["GET"];
  } else if (segments.length === 1 && segments[0] === "preferences") {
    path = "/api/v1/alerts/preferences";
    methods = ["GET", "PUT"];
  } else if (segments.length === 2 && segments[1] === "ack" && /^[a-zA-Z0-9_-]{1,64}$/.test(segments[0])) {
    path = `/api/v1/alerts/${segments[0]}/ack`;
    methods = ["POST"];
  } else {
    return fail(404, "NOT_FOUND", "Unknown alerts endpoint.");
  }
  if (!methods.includes(request.method)) {
    return new Response(null, { status: 405, headers: { ...privateHeaders, Allow: methods.join(", ") } });
  }

  const { search, searchParams } = request.nextUrl;
  if (search && (path !== "/api/v1/alerts" || search.length > 1024 || [...searchParams.keys()].some((key) => !filterKeys.has(key)))) {
    return fail(400, "INVALID_REQUEST", "The alerts filters are invalid.");
  }

  const headers = new Headers({ Accept: "application/json", Cookie: authCookieHeader((name) =>
    request.method !== "GET" || name === sessionCookie ? request.cookies.get(name)?.value : undefined) });

  try {
    let body: string | undefined;
    if (request.method !== "GET") {
      const origin = request.headers.get("origin");
      const token = request.headers.get("x-csrf-token");
      if (origin !== config.publicOrigin || !token) return fail(403, "CSRF_FAILED", "The request could not be verified.");
      headers.set("Origin", origin);
      headers.set("X-CSRF-Token", token);

      const payload = await readBoundedBody(request, 1024);
      if (payload === null) return fail(413, "PAYLOAD_TOO_LARGE", "The request is too large.");
      if (request.method === "PUT") {
        if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")) {
          return fail(415, "UNSUPPORTED_MEDIA_TYPE", "Send preferences as JSON.");
        }
        headers.set("Content-Type", "application/json");
        body = payload;
      } else if (payload) return fail(400, "INVALID_REQUEST", "Acknowledgement does not have a request body.");
    }

    const response = await fetch(`${config.upstream}${path}${search}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
    });
    if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) {
      await response.body?.cancel();
      return fail(502, "ALERTS_UNAVAILABLE", "Alerts are temporarily unavailable.");
    }
    return new Response(response.body, { status: response.status, headers: { ...privateHeaders, "Content-Type": "application/json" } });
  } catch {
    return fail(503, "ALERTS_UNAVAILABLE", "Alerts are temporarily unavailable.");
  }
}

export { proxy as GET, proxy as POST, proxy as PUT };
