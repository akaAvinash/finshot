import { inboxAlertLinkKinds, inboxSeverities, inboxSources, type AlertPreferences, type InAppPreferences, type InboxAlert, type InboxPage, type InboxStatus } from "./alerts-types";

const root = "/api/v1/alerts";

export class AlertRequestError extends Error {
  constructor(public readonly status: number) {
    super("Alerts request failed");
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function time(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function member(values: readonly string[], value: unknown) {
  return typeof value === "string" && values.includes(value);
}

function alert(value: unknown): value is InboxAlert {
  return record(value) && typeof value.id === "string" && /^[a-zA-Z0-9_-]{1,64}$/.test(value.id) &&
    typeof value.title === "string" && typeof value.message === "string" && typeof value.kind === "string" &&
    member(inboxSeverities, value.severity) && member(inboxSources, value.source) &&
    (value.environment === null || value.environment === "PAPER" || value.environment === "DEMO") &&
    time(value.occurredAt) && time(value.createdAt) && (value.acknowledgedAt === null || time(value.acknowledgedAt)) &&
    (value.link === null || (record(value.link) && typeof value.link.id === "string" &&
      member(inboxAlertLinkKinds, value.link.kind)));
}

function page(value: unknown): value is InboxPage {
  if (!record(value) || !time(value.asOf) || !Array.isArray(value.items) || !value.items.every(alert) ||
      !(value.nextCursor === null || (typeof value.nextCursor === "string" && value.nextCursor.length > 0)) || !record(value.unread)) return false;
  const unread = value.unread;
  return ["total", ...inboxSeverities].every((key) => typeof unread[key] === "number" && Number.isSafeInteger(unread[key]) && unread[key] >= 0);
}

function preferences(value: unknown): value is AlertPreferences {
  return record(value) && record(value.inApp) && value.inApp.critical === true && typeof value.inApp.warning === "boolean" &&
    typeof value.inApp.info === "boolean" && (value.updatedAt === null || time(value.updatedAt)) && Array.isArray(value.channels) &&
    value.channels.every((item: unknown) => record(item) && member(["email", "sms", "push"], item.channel) && item.available === false && item.enabled === false);
}

function csrf(value: unknown): value is { csrfToken: string; context: "session" | "pre_login" } {
  return record(value) && (value.context === "session" || value.context === "pre_login") &&
    typeof value.csrfToken === "string" && value.csrfToken.length > 0;
}

async function request<T>(url: string, validate: (value: unknown) => value is T, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, cache: "no-store", mode: "same-origin", redirect: "error" });
  if (!response.ok) throw new AlertRequestError(response.status);
  const body: unknown = await response.json().catch(() => null);
  if (!validate(body)) throw new AlertRequestError(502);
  return body;
}

async function writeHeaders() {
  const { csrfToken, context } = await request("/api/v1/auth/csrf", csrf);
  if (context !== "session") throw new AlertRequestError(401);
  return new Headers({ "X-CSRF-Token": csrfToken });
}

export function listInbox(filters: { status: InboxStatus; source: string; severity: string }, cursor: string | null, signal: AbortSignal) {
  const query = new URLSearchParams({ status: filters.status });
  if (filters.source !== "all") query.set("source", filters.source);
  if (filters.severity !== "all") query.set("severity", filters.severity);
  if (cursor) query.set("cursor", cursor);
  return request(`${root}?${query}`, page, { signal });
}

export async function acknowledgeInboxAlert(id: string) {
  return request(`${root}/${encodeURIComponent(id)}/ack`, alert, { method: "POST", headers: await writeHeaders() });
}

export function readAlertPreferences(signal: AbortSignal) {
  return request(`${root}/preferences`, preferences, { signal });
}

export async function saveAlertPreferences(inApp: InAppPreferences) {
  const headers = await writeHeaders();
  headers.set("Content-Type", "application/json");
  return request(`${root}/preferences`, preferences, { method: "PUT", headers, body: JSON.stringify({ inApp }) });
}
