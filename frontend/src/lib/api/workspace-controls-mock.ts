import { maxDisplayName, sampleSettingsCode, validateDemoRisk, WorkspacePreviewError } from "../workspace-controls";
import { waitForMock } from "./mock-delay";
import { retentionOptions, workspaceTimezones, type AlertsSnapshot, type SettingsCommand, type SettingsSnapshot, type WorkspaceAlert, type WorkspaceControlsClient } from "./workspace-controls-types";

const fixtureTime = "2026-11-23T10:00:00.000Z";
const staleTime = "2026-11-23T09:51:00.000Z";

function fixtureSettings(): SettingsSnapshot {
  return {
    source: "demo", environment: "DEMO", asOf: fixtureTime, timezone: "Asia/Kolkata", displayName: "Demo Trader",
    maskedPhone: "+91 •••••• 3210", phoneVerified: false,
    notifications: { inAppUpdates: true, emailDigest: false, criticalSms: false },
    retentionDays: 90, risk: { dailyLossPaise: 250_000, maxTrades: 10 }, audit: [],
    sessions: [
      { id: "this-browser", name: "This browser", current: true, lastSeenAt: "2026-11-23T09:48:00.000Z", revokedAt: null },
      { id: "sample-tablet", name: "Sample tablet", current: false, lastSeenAt: "2026-11-22T13:45:00.000Z", revokedAt: null },
    ],
  };
}

function fixtureAlerts(): WorkspaceAlert[] {
  return [
    { id: "risk-limit", title: "Paper risk limit reached", description: "The demo daily loss limit blocked a sample order intent.", source: "risk", severity: "critical", createdAt: "2026-11-23T09:58:00.000Z", acknowledgedAt: null },
    { id: "broker-offline", title: "Demo broker disconnected", description: "The sample account session expired. Reconnect is available in the Brokers preview.", source: "brokers", severity: "critical", createdAt: "2026-11-23T09:54:00.000Z", acknowledgedAt: null },
    { id: "stale-candle", title: "Market snapshot is stale", description: "The sample quote timestamp is older than the freshness window. Affected paper actions are paused.", source: "markets", severity: "critical", createdAt: "2026-11-23T09:49:00.000Z", acknowledgedAt: null },
    { id: "order-rejected", title: "Paper order rejected", description: "The simulated order exceeded the available paper balance.", source: "paper", severity: "critical", createdAt: "2026-11-23T09:42:00.000Z", acknowledgedAt: null },
    { id: "paper-halt", title: "Paper kill switch activated", description: "A previous demo replay halted and cleared its pending paper actions.", source: "paper", severity: "critical", createdAt: "2026-11-23T09:15:00.000Z", acknowledgedAt: "2026-11-23T09:20:00.000Z" },
    { id: "session-auth", title: "Sample sign-in needs review", description: "The demo shows an unrecognized device event. Review the sample sessions in Settings.", source: "security", severity: "critical", createdAt: "2026-11-23T08:54:00.000Z", acknowledgedAt: null },
    { id: "sync-delayed", title: "Sample sync delayed", description: "The demo broker activity update is taking longer than expected.", source: "brokers", severity: "warning", createdAt: "2026-11-23T08:34:00.000Z", acknowledgedAt: null },
    { id: "snapshot-ready", title: "Demo snapshot available", description: "The latest fixture is ready in the Markets workspace.", source: "markets", severity: "info", createdAt: "2026-11-23T07:45:00.000Z", acknowledgedAt: "2026-11-23T08:01:00.000Z" },
  ];
}

function applySettings(snapshot: SettingsSnapshot, command: SettingsCommand, at: string): SettingsSnapshot {
  if (command.kind !== "set-profile" && command.kind !== "set-notifications" && command.confirmationCode !== sampleSettingsCode) {
    throw new WorkspacePreviewError("Enter the sample verification code shown in this dialog.");
  }

  switch (command.kind) {
    case "set-profile": {
      const displayName = command.displayName.trim();
      if (!displayName || displayName.length > maxDisplayName || !workspaceTimezones.includes(command.timezone)) {
        throw new WorkspacePreviewError("Enter a display name of 1–48 characters and select a supported timezone.");
      }
      return { ...snapshot, displayName, timezone: command.timezone };
    }
    case "set-notifications":
      return { ...snapshot, notifications: { ...command.notifications } };
    case "verify-phone":
      if (snapshot.phoneVerified) throw new WorkspacePreviewError("The sample phone is already verified.");
      return { ...snapshot, phoneVerified: true };
    case "revoke-session": {
      const session = snapshot.sessions.find(({ id }) => id === command.sessionId);
      if (!session || session.current || session.revokedAt) throw new WorkspacePreviewError("This sample session cannot be revoked.");
      return { ...snapshot, sessions: snapshot.sessions.map((item) => item.id === session.id ? { ...item, revokedAt: at } : item) };
    }
    case "set-retention":
      if (!retentionOptions.includes(command.days)) throw new WorkspacePreviewError("Choose an available demo retention period.");
      return { ...snapshot, retentionDays: command.days };
    case "set-risk": {
      const error = validateDemoRisk(command.risk);
      if (error) throw new WorkspacePreviewError(error);
      return { ...snapshot, risk: { ...command.risk } };
    }
  }
}

export function createWorkspaceControlsMock(delay = 250): WorkspaceControlsClient {
  let settings = fixtureSettings();
  let alerts = fixtureAlerts();
  let asOf = fixtureTime;

  function nextSnapshotTime() {
    return new Date(Date.parse(asOf) + 60_000).toISOString();
  }

  function alertSnapshot(stale = false): AlertsSnapshot {
    const preferences = stale ? fixtureSettings() : settings;
    return {
      source: "demo", environment: "DEMO", asOf: stale ? staleTime : asOf, timezone: preferences.timezone,
      notifications: preferences.notifications,
      alerts: stale ? fixtureAlerts().filter(({ createdAt }) => createdAt <= staleTime) : alerts,
    };
  }

  return {
    async getAlerts({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario === "error") throw new Error("Demo inbox unavailable.");
      if (scenario === "empty" || scenario === "denied") return { status: scenario };
      return { status: scenario, data: alertSnapshot(scenario === "stale") };
    },
    async acknowledgeAlert(id, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario !== "ready") throw new Error("Acknowledgement requires current demo data.");
      const alert = alerts.find((item) => item.id === id);
      if (!alert) throw new WorkspacePreviewError("This demo alert is unavailable.");
      if (!alert.acknowledgedAt) {
        asOf = nextSnapshotTime();
        alerts = alerts.map((item) => item.id === alert.id ? { ...item, acknowledgedAt: asOf } : item);
      }
      return alertSnapshot();
    },
    async getSettings({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario === "error") throw new Error("Demo settings unavailable.");
      if (scenario === "empty" || scenario === "denied") return { status: scenario };
      return { status: scenario, data: scenario === "stale" ? { ...fixtureSettings(), asOf: staleTime } : { ...settings, asOf } };
    },
    async updateSettings(command, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario !== "ready") throw new Error("Updating preferences requires current demo data.");
      const at = nextSnapshotTime();
      const next = applySettings(settings, command, at);
      asOf = at;
      settings = { ...next, asOf, audit: [{ id: `change-${next.audit.length + 1}`, action: command.kind, at }, ...next.audit] };
      return settings;
    },
  };
}
