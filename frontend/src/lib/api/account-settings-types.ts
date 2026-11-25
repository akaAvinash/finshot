export const accountTimezones = ["Asia/Kolkata", "UTC"] as const;
export type AccountTimezone = typeof accountTimezones[number];
export type AccountProfile = { displayName: string | null; timezone: AccountTimezone; phoneMasked: string };
export type AccountProfileUpdate = { displayName: string; timezone: AccountTimezone };
export type AccountSession = {
  id: string;
  deviceLabel: string | null;
  createdAt: string;
  lastSeenAt: string;
  expiresAt: string;
  current: boolean;
};

export function isSessionId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
}
