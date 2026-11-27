export const inboxSeverities = ["critical", "warning", "info"] as const;
export const inboxSources = ["paper", "brokers", "agents", "security"] as const;
export const inboxAlertLinkKinds = ["paper-trade", "paper-order", "paper-replay", "broker", "broker-connection", "session"] as const;

export type InboxSeverity = (typeof inboxSeverities)[number];
export type InboxSource = (typeof inboxSources)[number];
export type InboxStatus = "all" | "unread";

export type InboxAlert = {
  id: string;
  kind: string;
  source: InboxSource;
  severity: InboxSeverity;
  environment: "PAPER" | "DEMO" | null;
  title: string;
  message: string;
  occurredAt: string;
  createdAt: string;
  acknowledgedAt: string | null;
  link: { kind: (typeof inboxAlertLinkKinds)[number]; id: string } | null;
};

export type InboxPage = {
  asOf: string;
  items: InboxAlert[];
  nextCursor: string | null;
  unread: { total: number; critical: number; warning: number; info: number };
};

export type InAppPreferences = { warning: boolean; info: boolean };
export type AlertPreferences = {
  inApp: InAppPreferences & { critical: true };
  channels: Array<{ channel: "email" | "sms" | "push"; available: false; enabled: false }>;
  updatedAt: string | null;
};
