import { AuthError, requestAccount, writeAccount } from "@/lib/auth/browser-client";

export async function stagingRequest<T>(path: string, parse: (value: unknown) => T | undefined, signal?: AbortSignal, body?: object) {
  const url = `/api/v1/${path}`;
  const response = body === undefined
    ? await requestAccount(url, { signal })
    : await writeAccount(url, "POST", body, signal);
  const value: unknown = await response.json().catch(() => undefined);
  const result = parse(value);
  if (result === undefined) {
    throw new AuthError(502, "INVALID_RESPONSE", undefined, undefined, response.headers.get("X-Request-ID") ?? undefined);
  }
  return result;
}

export function stagingError(error: unknown, fallback: string) {
  if (!(error instanceof AuthError)) return fallback;
  if (error.status === 401) return "Your session expired. Sign in and try again.";
  if (error.status === 403) return "This action could not be authorized. Reload the page and try again.";
  if (error.status === 429 && error.retryAfter) {
    return `Too many requests. Try again in ${error.retryAfter} ${error.retryAfter === 1 ? "second" : "seconds"}.`;
  }
  if ([400, 404, 409, 422].includes(error.status) && error.detail && error.detail.length <= 240) {
    return error.detail;
  }
  return error.requestId && error.status >= 500 ? `${fallback} Request ID ${error.requestId}.` : fallback;
}

export function isUnconfirmedStagingWrite(error: unknown) {
  return !(error instanceof AuthError) || error.status === 408 || error.status >= 500;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

export function isOneOf<const T extends string>(value: unknown, values: readonly T[]): value is T {
  return values.some((item) => item === value);
}

export function hasStrings(row: Record<string, unknown>, keys: readonly string[]) {
  return keys.every((key) => typeof row[key] === "string");
}

export function hasIntegers(row: Record<string, unknown>, keys: readonly string[]) {
  return keys.every((key) => Number.isSafeInteger(row[key]));
}

export function isSnapshot(value: unknown, environment: "DEMO" | "PAPER"): value is Record<string, unknown> {
  return isRecord(value) && value.source === "demo" && value.environment === environment && isTimestamp(value.asOf);
}

export function parseSnapshot<T>(value: unknown, guard: (data: unknown) => data is T) {
  if (isRecord(value) && value.status === "ready" && guard(value.data)) return { status: "ready" as const, data: value.data };
}
