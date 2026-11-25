import type { AlertSeverity, AlertSource, SettingsCommand, WorkspaceRisk, WorkspaceTimezone } from "./api/workspace-controls-types";

export const sampleSettingsCode = "246810";
export const maxDemoLossPaise = 10_000_000;
export const maxDemoTrades = 100;
export const maxDisplayName = 48;

export class WorkspacePreviewError extends Error {}

export const alertSeverityLabels = { critical: "Critical", warning: "Warning", info: "Info" } as const satisfies Record<AlertSeverity, string>;
export const alertSourceLabels = { risk: "Risk policy", brokers: "Brokers", markets: "Markets", paper: "Paper trading", security: "Account security" } as const satisfies Record<AlertSource, string>;
export const timezoneLabels = { "Asia/Kolkata": "India Standard Time (IST)", UTC: "Coordinated Universal Time (UTC)" } as const satisfies Record<WorkspaceTimezone, string>;

export const settingsActions = {
  "set-profile": "Profile preferences updated", "set-notifications": "Notification preferences updated",
  "verify-phone": "Sample phone verified", "revoke-session": "Sample session revoked",
  "set-retention": "Demo retention preference updated", "set-risk": "Demo risk limits updated",
} as const satisfies Record<SettingsCommand["kind"], string>;

const dateOptions = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" } as const;
const timestamps = {
  "Asia/Kolkata": new Intl.DateTimeFormat("en-IN", { ...dateOptions, timeZone: "Asia/Kolkata" }),
  UTC: new Intl.DateTimeFormat("en-IN", { ...dateOptions, timeZone: "UTC" }),
};

export function formatWorkspaceTime(value: string, timezone: WorkspaceTimezone) {
  return `${timestamps[timezone].format(new Date(value))} ${timezone === "Asia/Kolkata" ? "IST" : "UTC"}`;
}

export function validateDemoRisk(risk: WorkspaceRisk) {
  if (!Number.isInteger(risk.dailyLossPaise) || risk.dailyLossPaise < 100 || risk.dailyLossPaise > maxDemoLossPaise) {
    return "Enter a daily loss limit between ₹1 and ₹1,00,000.";
  }
  if (!Number.isInteger(risk.maxTrades) || risk.maxTrades < 1 || risk.maxTrades > maxDemoTrades) {
    return "Enter a maximum of 1–100 trades per day.";
  }
  return null;
}
