import { AuthError, requestAccount, writeAccount } from "@/lib/auth/browser-client";
import { isSessionId, type AccountProfile, type AccountProfileUpdate, type AccountSession } from "./account-settings-types";

const profilePath = "/api/v1/settings/profile";
const sessionsPath = "/api/v1/auth/sessions";

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function date(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function profile(value: unknown): value is AccountProfile {
  return record(value) && (value.displayName === null || typeof value.displayName === "string") &&
    (value.timezone === "Asia/Kolkata" || value.timezone === "UTC") && typeof value.phoneMasked === "string";
}

function accountSession(value: unknown): value is AccountSession {
  return record(value) && isSessionId(value.id) && (value.deviceLabel === null || typeof value.deviceLabel === "string") &&
    date(value.createdAt) && date(value.lastSeenAt) && date(value.expiresAt) && typeof value.current === "boolean";
}

async function readProfile(response: Response): Promise<AccountProfile> {
  const value: unknown = await response.json();
  if (!profile(value)) throw new AuthError(502);
  return value;
}

export async function getAccountProfile(signal: AbortSignal) {
  return readProfile(await requestAccount(profilePath, { signal }));
}

export async function saveAccountProfile(update: AccountProfileUpdate) {
  return readProfile(await writeAccount(profilePath, "PUT", update));
}

export async function listAccountSessions(signal: AbortSignal): Promise<AccountSession[]> {
  const value: unknown = await (await requestAccount(sessionsPath, { signal })).json();
  if (!record(value) || !Array.isArray(value.sessions) || !value.sessions.every(accountSession)) throw new AuthError(502);
  return value.sessions;
}

export async function endAccountSession(id: string) {
  if (!isSessionId(id)) throw new AuthError(400);
  const response = await writeAccount(`${sessionsPath}/${id}`, "DELETE");
  if (response.status !== 204) throw new AuthError(502);
}
