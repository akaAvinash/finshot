// @vitest-environment node
import { describe, expect, it } from "vitest";
import { applyBrokerAction, createBrokerMock } from "@/lib/api/broker-mock";
import type { BrokerClient, BrokerId, BrokerSnapshot } from "@/lib/api/broker-types";
import { formatBrokerTime, getBrokerStatus } from "@/lib/brokers";

async function load(client: BrokerClient) {
  const result = await client.getBrokers();
  if (result.status !== "ready") throw new Error("Expected ready broker data");
  return result.data;
}

function account(snapshot: BrokerSnapshot, provider: BrokerId) {
  return snapshot.connections.find((entry) => entry.provider === provider)?.account ?? null;
}

describe("broker demo", () => {
  it("returns masked accounts, read scopes and expiry relative to the fixture time", async () => {
    const initial = await load(createBrokerMock());
    const zerodha = account(initial, "zerodha");
    const fyers = account(initial, "fyers");

    expect(initial).toMatchObject({ source: "demo", environment: "DEMO" });
    expect(zerodha?.maskedAccountId).toMatch(/^•••• [0-9]{4}$/);
    expect(zerodha?.scopes.every((scope) => scope.endsWith("_read"))).toBe(true);
    expect(getBrokerStatus(zerodha, initial.asOf)).toBe("connected");
    expect(getBrokerStatus(fyers, initial.asOf)).toBe("expired");
    if (!zerodha) throw new Error("Expected Zerodha fixture");
    expect(getBrokerStatus(zerodha, zerodha.expiresAt)).toBe("expired");
    expect(formatBrokerTime(initial.asOf)).toContain("15:30 IST");
  });

  it("reconnects and syncs an expired account while preserving prior state and activity", async () => {
    const initial = await load(createBrokerMock());
    const reconnected = applyBrokerAction(initial, "fyers", "reconnect");
    const synced = applyBrokerAction(reconnected, "fyers", "sync");

    expect(getBrokerStatus(account(reconnected, "fyers"), reconnected.asOf)).toBe("connected");
    expect(account(reconnected, "fyers")?.lastSyncedAt).toBeNull();
    expect(account(synced, "fyers")?.lastSyncedAt).toBe(synced.asOf);
    expect(account(synced, "zerodha")).toEqual(account(initial, "zerodha"));
    expect(getBrokerStatus(account(initial, "fyers"), initial.asOf)).toBe("expired");
    expect(synced.events.slice(0, initial.events.length)).toEqual(initial.events);
    expect(synced.events.slice(-2).map(({ action }) => action)).toEqual(["reconnect", "sync"]);
  });

  it("disconnects and reconnects through the allowed new-connection flow", async () => {
    const initial = await load(createBrokerMock());
    const disconnected = applyBrokerAction(initial, "zerodha", "disconnect");
    expect(account(disconnected, "zerodha")).toBeNull();
    expect(disconnected.events.at(-1)?.action).toBe("disconnect");
    expect(() => applyBrokerAction(disconnected, "zerodha", "sync")).toThrow("not ready");
    expect(() => applyBrokerAction(initial, "fyers", "sync")).toThrow("not ready");
    expect(() => applyBrokerAction(initial, "zerodha", "connect")).toThrow("not ready");
    expect(account(applyBrokerAction(disconnected, "zerodha", "connect"), "zerodha")?.lastSyncedAt).toBeNull();
  });

  it("supports preview failures, isolates instances and rejects unavailable actions", async () => {
    const client = createBrokerMock();
    const separate = createBrokerMock();
    const controller = new AbortController();
    const cancelled = client.getBrokers({ signal: controller.signal });
    controller.abort();

    await Promise.all([
      expect(cancelled).rejects.toHaveProperty("name", "AbortError"),
      expect(client.getBrokers({ scenario: "empty" })).resolves.toEqual({ status: "empty" }),
      expect(client.getBrokers({ scenario: "denied" })).resolves.toEqual({ status: "denied" }),
      expect(client.getBrokers({ scenario: "stale" })).resolves.toMatchObject({ status: "stale" }),
      expect(client.getBrokers({ scenario: "error" })).rejects.toThrow("Simulated broker request failure"),
      expect(client.sendBrokerAction("zerodha", "sync", { scenario: "stale" })).rejects.toThrow("fresh demo broker snapshot"),
    ]);
    await client.sendBrokerAction("zerodha", "disconnect");
    expect(account(await load(client), "zerodha")).toBeNull();
    expect(account(await load(separate), "zerodha")).not.toBeNull();
  });
});
