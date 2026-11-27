import "server-only";

import { isSessionId } from "@/lib/api/account-settings-types";

export const sessionCookie = "__Host-tradeo_session";
const csrfCookie = "__Host-tradeo_csrf";

export const authEndpoints = {
  csrf: "GET",
  me: "GET",
  sessions: "GET",
  "otp/request": "POST",
  "otp/verify": "POST",
  "login/totp": "POST",
  "login/recovery": "POST",
  "login/tester": "POST",
  "totp/enroll": "POST",
  "totp/confirm": "POST",
  "totp/recovery-codes": "POST",
  "step-up": "POST",
  logout: "POST",
} as const;

export type AuthEndpoint = keyof typeof authEndpoints | `sessions/${string}`;

export function getAuthEndpoint(path: string): AuthEndpoint | null {
  if (Object.hasOwn(authEndpoints, path)) return path as keyof typeof authEndpoints;
  return path.startsWith("sessions/") && isSessionId(path.slice(9)) ? path as `sessions/${string}` : null;
}

export function authEndpointMethod(endpoint: AuthEndpoint) {
  return endpoint.startsWith("sessions/") ? "DELETE" : authEndpoints[endpoint as keyof typeof authEndpoints];
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
    method: authEndpointMethod(endpoint),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(8000),
  });
}

export function authResponseCookies(upstream: Response) {
  return upstream.headers.getSetCookie().filter((cookie) => cookie.startsWith(`${sessionCookie}=`) || cookie.startsWith(`${csrfCookie}=`));
}
