export const alertSeverities = ["critical", "warning", "info"] as const;
export const alertSources = ["risk", "brokers", "markets", "paper", "security"] as const;
export const workspaceTimezones = ["Asia/Kolkata", "UTC"] as const;
export const retentionOptions = [30, 90, 180] as const;

export type AlertSeverity = (typeof alertSeverities)[number];
export type AlertSource = (typeof alertSources)[number];
export type WorkspaceTimezone = (typeof workspaceTimezones)[number];
export type RetentionDays = (typeof retentionOptions)[number];
export type WorkspaceScenario = "ready" | "stale" | "empty" | "denied" | "error";

export type WorkspaceAlert = {
  id: string;
  title: string;
  description: string;
  source: AlertSource;
  severity: AlertSeverity;
  createdAt: string;
  acknowledgedAt: string | null;
};

export type NotificationPreferences = {
  inAppUpdates: boolean;
  emailDigest: boolean;
  criticalSms: boolean;
};

type DemoSnapshot = { source: "demo"; environment: "DEMO"; asOf: string; timezone: WorkspaceTimezone };
export type AlertsSnapshot = DemoSnapshot & { alerts: readonly WorkspaceAlert[]; notifications: NotificationPreferences };

export type DemoSession = { id: string; name: string; current: boolean; lastSeenAt: string; revokedAt: string | null };
export type WorkspaceRisk = { dailyLossPaise: number; maxTrades: number };
export type SettingsAudit = { id: string; action: SettingsCommand["kind"]; at: string };

export type SettingsSnapshot = DemoSnapshot & {
  displayName: string;
  maskedPhone: string;
  phoneVerified: boolean;
  sessions: readonly DemoSession[];
  notifications: NotificationPreferences;
  retentionDays: RetentionDays;
  risk: WorkspaceRisk;
  audit: readonly SettingsAudit[];
};

export type SensitiveSettingsChange =
  | { kind: "verify-phone" }
  | { kind: "revoke-session"; sessionId: string }
  | { kind: "set-retention"; days: RetentionDays }
  | { kind: "set-risk"; risk: WorkspaceRisk };

export type SettingsCommand =
  | { kind: "set-profile"; displayName: string; timezone: WorkspaceTimezone }
  | { kind: "set-notifications"; notifications: NotificationPreferences }
  | (SensitiveSettingsChange & { confirmationCode: string });

export type WorkspaceResult<T> = { status: "ready" | "stale"; data: T } | { status: "empty" | "denied" };
export type WorkspaceRequestOptions = { scenario?: WorkspaceScenario; signal?: AbortSignal };

export interface WorkspaceControlsClient {
  getAlerts(options?: WorkspaceRequestOptions): Promise<WorkspaceResult<AlertsSnapshot>>;
  acknowledgeAlert(id: string, options?: WorkspaceRequestOptions): Promise<AlertsSnapshot>;
  getSettings(options?: WorkspaceRequestOptions): Promise<WorkspaceResult<SettingsSnapshot>>;
  updateSettings(command: SettingsCommand, options?: WorkspaceRequestOptions): Promise<SettingsSnapshot>;
}
