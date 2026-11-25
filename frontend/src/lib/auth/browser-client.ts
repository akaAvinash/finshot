import { normalizeIndianMobile } from "@/lib/preview-auth/validation";

type LoginState =
  | { step: "phone"; error?: string }
  | { step: "code"; phone: string; error?: string; challengeId?: string };

const authRoot = "/api/v1/auth";

class AuthError extends Error {
  constructor(public readonly status: number, public readonly code?: string, public readonly retryAfter?: number) {
    super("Auth request failed");
  }
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

async function postAuth(path: "otp/request" | "otp/verify" | "logout", body?: Record<string, string>) {
  const csrf = await (await requestAuth("csrf")).json();
  if (typeof csrf?.csrfToken !== "string" || !csrf.csrfToken) throw new AuthError(502);

  const headers = new Headers({ "X-CSRF-Token": csrf.csrfToken });
  if (body) headers.set("Content-Type", "application/json");
  return requestAuth(path, { method: "POST", headers, body: body ? JSON.stringify(body) : undefined });
}

export async function stagingLogin(state: LoginState, formData: FormData): Promise<LoginState> {
  if (formData.get("intent") === "change-phone") return { step: "phone" };

  try {
    if (state.step === "phone" || formData.get("intent") === "resend") {
      const phone = state.step === "code" ? state.phone : normalizeIndianMobile(String(formData.get("phone") ?? ""));
      if (!phone) return { step: "phone", error: "Enter a valid 10-digit Indian mobile number." };
      const challenge = await (await postAuth("otp/request", { phone: `+91${phone}` })).json();
      if (typeof challenge?.challengeId !== "string" || !challenge.challengeId) throw new AuthError(502);
      return { step: "code", phone, challengeId: challenge.challengeId };
    }

    const code = String(formData.get("code") ?? "").trim();
    if (!/^\d{6}$/.test(code)) return { ...state, error: "Enter the six-digit code." };
    if (!state.challengeId) return { step: "phone", error: "Request a new code to continue." };
    await postAuth("otp/verify", { challengeId: state.challengeId, code });
    window.location.replace("/dashboard");
    return state;
  } catch (error) {
    let message = "Sign-in is temporarily unavailable. Try again shortly.";
    if (error instanceof AuthError) {
      if (error.status === 429) {
        const wait = error.retryAfter ? ` Try again in ${error.retryAfter} seconds.` : " Try again later.";
        message = `Too many attempts.${wait}`;
      } else if (error.code === "OTP_DELIVERY_UNAVAILABLE") {
        message = "Code delivery is unavailable. Try again later.";
      } else if (error.status === 403) {
        message = "This request could not be verified. Reload the page and try again.";
      } else if (error.code === "INVALID_OTP") {
        message = "This code is invalid, expired, or used. Try again or request a new code.";
      }
    }
    return { ...state, error: message };
  }
}

export async function stagingSignOut() {
  try {
    const response = await postAuth("logout");
    if (response.status !== 204) throw new AuthError(502);
    window.location.replace("/login");
    return null;
  } catch {
    return "We couldn’t confirm sign-out. Try again.";
  }
}

export type { LoginState };
