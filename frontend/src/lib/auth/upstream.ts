import "server-only";

export const sessionCookie = "__Host-tradeo_session";
const csrfCookie = "__Host-tradeo_csrf";

export const authEndpoints = {
  csrf: "GET",
  me: "GET",
  "otp/request": "POST",
  "otp/verify": "POST",
  logout: "POST",
} as const;

export type AuthEndpoint = keyof typeof authEndpoints;

export function getAuthEndpoint(path: string): AuthEndpoint | null {
  return Object.hasOwn(authEndpoints, path) ? path as AuthEndpoint : null;
}

export function authCookieHeader(readCookie: (name: string) => string | undefined) {
  return [sessionCookie, csrfCookie].flatMap((name) => {
    const value = readCookie(name);
    return value ? [`${name}=${encodeURIComponent(value)}`] : [];
  }).join("; ");
}

export function requestUpstreamAuth(origin: string, endpoint: AuthEndpoint, init: RequestInit) {
  return fetch(`${origin}/api/v1/auth/${endpoint}`, {
    ...init,
    method: authEndpoints[endpoint],
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(8000),
  });
}

export function authProxyResponse(upstream: Response) {
  const headers = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
  for (const name of ["content-type", "retry-after", "x-request-id"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) {
    if (cookie.startsWith(`${sessionCookie}=`) || cookie.startsWith(`${csrfCookie}=`)) {
      headers.append("Set-Cookie", cookie);
    }
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
