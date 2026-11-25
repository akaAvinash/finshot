import { describe, expect, it } from "vitest";
import { createWorkspaceControlsMock } from "@/lib/api/workspace-controls-mock";
import type { SettingsCommand } from "@/lib/api/workspace-controls-types";
import { sampleSettingsCode } from "@/lib/workspace-controls";

describe("Alerts and Settings demo adapter", () => {
  it("acknowledges alerts idempotently and keeps stale snapshots historical", async () => {
    const client = createWorkspaceControlsMock(0);
    const saved = await client.acknowledgeAlert("risk-limit");
    expect(saved.alerts[0]).toMatchObject({ id: "risk-limit", severity: "critical", acknowledgedAt: saved.asOf });
    await expect(client.acknowledgeAlert("risk-limit")).resolves.toEqual(saved);
    await expect(client.acknowledgeAlert("missing")).rejects.toThrow(/unavailable/);

    const stale = await client.getAlerts({ scenario: "stale" });
    if (stale.status !== "stale") throw new Error("Expected the stale inbox.");
    expect(stale.data.alerts.every(({ createdAt }) => createdAt <= stale.data.asOf)).toBe(true);
    await expect(client.acknowledgeAlert("stale-candle", { scenario: "stale" })).rejects.toThrow(/current demo data/);
  });

  it("shares notification and timezone preferences only within the workspace instance", async () => {
    const client = createWorkspaceControlsMock(0);
    await client.updateSettings({ kind: "set-profile", displayName: "  Sample desk  ", timezone: "UTC" });
    const notifications = { inAppUpdates: false, emailDigest: true, criticalSms: true };
    const settings = await client.updateSettings({ kind: "set-notifications", notifications });
    expect(settings).toMatchObject({ source: "demo", displayName: "Sample desk", timezone: "UTC", notifications });
    expect(settings.audit.map(({ action }) => action)).toEqual(["set-notifications", "set-profile"]);
    await expect(client.getAlerts()).resolves.toMatchObject({ status: "ready", data: { timezone: "UTC", notifications } });
    await expect(createWorkspaceControlsMock(0).getSettings()).resolves.toMatchObject({ status: "ready", data: { timezone: "Asia/Kolkata", audit: [] } });
  });

  it("checks confirmation and risk limits before writing a code-free demo audit trail", async () => {
    const client = createWorkspaceControlsMock(0);
    const before = await client.getSettings();
    await expect(client.updateSettings({ kind: "verify-phone" } as SettingsCommand)).rejects.toThrow(/sample verification code/);
    await expect(client.updateSettings({ kind: "verify-phone", confirmationCode: "000000" })).rejects.toThrow(/sample verification code/);
    await expect(client.updateSettings({ kind: "revoke-session", sessionId: "this-browser", confirmationCode: sampleSettingsCode })).rejects.toThrow(/cannot be revoked/);
    await expect(client.updateSettings({ kind: "set-risk", risk: { dailyLossPaise: 250_000, maxTrades: 101 }, confirmationCode: sampleSettingsCode })).rejects.toThrow(/1–100 trades/);
    await expect(client.getSettings()).resolves.toEqual(before);

    await client.updateSettings({ kind: "verify-phone", confirmationCode: sampleSettingsCode });
    await client.updateSettings({ kind: "revoke-session", sessionId: "sample-tablet", confirmationCode: sampleSettingsCode });
    await client.updateSettings({ kind: "set-retention", days: 30, confirmationCode: sampleSettingsCode });
    const kept = await client.updateSettings({ kind: "set-risk", risk: { dailyLossPaise: 125_050, maxTrades: 8 }, confirmationCode: sampleSettingsCode });
    expect(kept).toMatchObject({ phoneVerified: true, retentionDays: 30, risk: { dailyLossPaise: 125_050, maxTrades: 8 } });
    expect(kept.sessions[1].revokedAt).toBeTruthy();
    expect(kept.audit.map(({ action }) => action)).toEqual(["set-risk", "set-retention", "revoke-session", "verify-phone"]);
    expect(JSON.stringify(kept)).not.toContain(sampleSettingsCode);
  });
});
