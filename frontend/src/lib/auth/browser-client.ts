const authRoot = "/api/v1/auth";

export class AuthError extends Error {
  constructor(public readonly status: number, public readonly code?: string, public readonly retryAfter?: number) {
    super("Auth request failed");
  }
}

type CsrfContext = "pre_login" | "session";
let sessionCsrfToken: string | undefined;

export type EmailChallenge = { challengeId: string; expiresAt: string; resendAvailableAt: string };
export type AuthenticatorEnrollment = { secret: string; otpauthUri: string; expiresAt: string };
export const recoveryCodePattern = /^[A-Z2-7]{5}-?[A-Z2-7]{5}$/i;

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

async function requestAuth(path: string, init?: RequestInit) {
  const response = await fetch(`${authRoot}/${path}`, { ...init, cache: "no-store", mode: "same-origin", redirect: "error" });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    const retryAfter = Number(response.headers.get("Retry-After"));
    throw new AuthError(response.status, error?.code, Number.isSafeInteger(retryAfter) && retryAfter > 0 ? retryAfter : undefined);
  }
  return response;
}

async function readCsrf(context?: CsrfContext) {
  const data = await (await requestAuth("csrf")).json();
  if (typeof data?.csrfToken !== "string" || !data.csrfToken || !["pre_login", "session"].includes(data.context)) throw new AuthError(502);
  if (context && context !== data.context) throw new AuthError(context === "session" ? 401 : 409, "AUTH_CONTEXT_CHANGED");
  if (data.context === "session") sessionCsrfToken = data.csrfToken;
  else sessionCsrfToken = undefined;
  return data.csrfToken as string;
}

type AuthWrite = "otp/request" | "otp/verify" | "totp/enroll" | "totp/confirm" | "logout";

async function postAuth(path: AuthWrite, context?: CsrfContext, body?: Record<string, string>) {
  function send(token: string) {
    const headers = new Headers({ "X-CSRF-Token": token });
    if (body) headers.set("Content-Type", "application/json");
    return requestAuth(path, { method: "POST", headers, body: body ? JSON.stringify(body) : undefined });
  }

  const cached = context === "session" ? sessionCsrfToken : undefined;
  if (!cached) return send(await readCsrf(context));

  try {
    return await send(cached);
  } catch (error) {
    if (!(error instanceof AuthError) || error.code !== "CSRF_FAILED") throw error;
    return send(await readCsrf(context));
  }
}

export async function requestSignInChallenge(email: string): Promise<EmailChallenge> {
  const response = await postAuth("otp/request", "pre_login", { email });
  const data = await response.json();
  if (response.status !== 202 || typeof data?.challengeId !== "string" || !data.challengeId ||
      !isTimestamp(data.expiresAt) || !isTimestamp(data.resendAvailableAt)) throw new AuthError(502);
  return { challengeId: data.challengeId, expiresAt: data.expiresAt, resendAvailableAt: data.resendAvailableAt };
}

async function readSignedIn(response: Response) {
  const data = await response.json();
  if (typeof data?.csrfToken !== "string" || !data.csrfToken || typeof data?.user?.totpEnabled !== "boolean") throw new AuthError(502);
  sessionCsrfToken = data.csrfToken;
  return data.user.totpEnabled as boolean;
}

export async function verifySignInChallenge(challengeId: string, proof: { code: string } | { recoveryCode: string }) {
  return readSignedIn(await postAuth("otp/verify", "pre_login", { challengeId, ...proof }));
}

export async function enrollAuthenticator(): Promise<AuthenticatorEnrollment> {
  const data = await (await postAuth("totp/enroll", "session")).json();
  if (typeof data?.secret !== "string" || !/^[A-Z2-7]{16,128}$/.test(data.secret) || typeof data.otpauthUri !== "string" ||
      data.otpauthUri.length > 1024 || !isTimestamp(data.expiresAt)) throw new AuthError(502);
  try {
    const uri = new URL(data.otpauthUri);
    if (uri.protocol !== "otpauth:" || uri.hostname !== "totp" || uri.searchParams.get("secret") !== data.secret) throw new AuthError(502);
  } catch {
    throw new AuthError(502);
  }
  return { secret: data.secret, otpauthUri: data.otpauthUri, expiresAt: data.expiresAt };
}

export async function confirmAuthenticator(code: string): Promise<string[]> {
  const data = await (await postAuth("totp/confirm", "session", { code })).json();
  const codes: unknown = data?.recoveryCodes;
  if (data?.totpEnabled !== true || !isTimestamp(data.stepUpUntil) || !Array.isArray(codes) || codes.length !== 10 ||
      !codes.every((value) => typeof value === "string" && /^[a-z2-7]{5}-[a-z2-7]{5}$/.test(value)) ||
      new Set(codes).size !== codes.length) throw new AuthError(502);
  return codes;
}

export function authRetryMessage(error: AuthError) {
  return error.retryAfter ? `Too many attempts. Try again in ${error.retryAfter} seconds.` : "Too many attempts. Try again later.";
}

export async function stagingSignOut() {
  try {
    const response = await postAuth("logout");
    if (response.status !== 204) throw new AuthError(502);
    sessionCsrfToken = undefined;
    window.location.replace("/login");
    return null;
  } catch {
    return "We couldn’t confirm sign-out. Try again.";
  }
}
