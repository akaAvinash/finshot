import { getBrokerStatus } from "@/lib/brokers";
import type { BrokerAction, BrokerClient, BrokerId, BrokerScope, BrokerSnapshot } from "./broker-types";
import { waitForMock } from "./mock-delay";

const scopes: readonly BrokerScope[] = ["profile_read", "holdings_read", "orders_read"];
const accountMasks: Record<BrokerId, string> = { zerodha: "•••• 4821", fyers: "•••• 0956" };
const actionsByStatus = {
  connected: ["sync", "disconnect"],
  expired: ["reconnect", "disconnect"],
  disconnected: ["connect"],
} as const satisfies Record<string, readonly BrokerAction[]>;

const fixture: BrokerSnapshot = {
  source: "demo",
  environment: "DEMO",
  asOf: "2026-11-23T10:00:00.000Z",
  connections: [
    {
      provider: "zerodha",
      account: {
        maskedAccountId: accountMasks.zerodha,
        connectedAt: "2026-11-23T03:40:00.000Z",
        expiresAt: "2026-11-23T13:00:00.000Z",
        lastSyncedAt: "2026-11-23T09:55:00.000Z",
        scopes,
      },
    },
    {
      provider: "fyers",
      account: {
        maskedAccountId: accountMasks.fyers,
        connectedAt: "2026-11-23T03:45:00.000Z",
        expiresAt: "2026-11-23T07:30:00.000Z",
        lastSyncedAt: "2026-11-23T07:25:00.000Z",
        scopes,
      },
    },
  ],
  events: [
    { id: "broker-event-1", provider: "zerodha", action: "connect", at: "2026-11-23T03:40:00.000Z" },
    { id: "broker-event-2", provider: "fyers", action: "connect", at: "2026-11-23T03:45:00.000Z" },
    { id: "broker-event-3", provider: "fyers", action: "sync", at: "2026-11-23T07:25:00.000Z" },
    { id: "broker-event-4", provider: "zerodha", action: "sync", at: "2026-11-23T09:55:00.000Z" },
  ],
};

export function applyBrokerAction(snapshot: BrokerSnapshot, provider: BrokerId, action: BrokerAction): BrokerSnapshot {
  const connection = snapshot.connections.find((entry) => entry.provider === provider);
  if (!connection) throw new Error("Unknown demo broker.");
  const status = getBrokerStatus(connection.account, snapshot.asOf);
  const allowedActions: readonly BrokerAction[] = actionsByStatus[status];
  if (!allowedActions.includes(action)) throw new Error("The demo broker is not ready for this action.");

  const asOf = new Date(Date.parse(snapshot.asOf) + 60_000).toISOString();
  let account = connection.account;
  switch (action) {
    case "disconnect":
      account = null;
      break;
    case "sync":
      if (!account || getBrokerStatus(account, asOf) !== "connected") throw new Error("Reconnect the demo account before syncing.");
      account = { ...account, lastSyncedAt: asOf };
      break;
    case "connect":
    case "reconnect":
      account = {
        maskedAccountId: accountMasks[provider],
        connectedAt: asOf,
        expiresAt: new Date(Date.parse(asOf) + 8 * 60 * 60_000).toISOString(),
        lastSyncedAt: null,
        scopes,
      };
      break;
  }

  return {
    ...snapshot,
    asOf,
    connections: snapshot.connections.map((entry) => entry.provider === provider ? { provider, account } : entry),
    events: [...snapshot.events, { id: `broker-event-${snapshot.events.length + 1}`, provider, action, at: asOf }],
  };
}

export function createBrokerMock(): BrokerClient {
  let snapshot = fixture;

  return {
    async getBrokers({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, 340);
      if (scenario === "error") throw new Error("Simulated broker request failure.");
      if (scenario === "empty" || scenario === "denied") return { status: scenario };
      return { status: scenario, data: structuredClone(snapshot) };
    },
    async sendBrokerAction(provider, action, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, 240);
      if (scenario !== "ready") throw new Error("A fresh demo broker snapshot is required.");
      snapshot = applyBrokerAction(snapshot, provider, action);
      return structuredClone(snapshot);
    },
  };
}
