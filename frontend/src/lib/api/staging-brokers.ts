import type { BrokerClient, BrokerSnapshot } from "./broker-types";
import { isOneOf, isRecord, isSnapshot, isTimestamp, parseSnapshot, stagingRequest } from "./staging-client";

const providers = ["zerodha", "fyers"] as const;
const actions = ["connect", "reconnect", "sync", "disconnect"] as const;
const scopes = ["profile_read", "holdings_read", "orders_read"] as const;

function isAccount(value: unknown) {
  return value === null || (isRecord(value) && typeof value.maskedAccountId === "string" &&
    /^•••• [0-9]{4}$/.test(value.maskedAccountId) && isTimestamp(value.connectedAt) && isTimestamp(value.expiresAt) &&
    (value.lastSyncedAt === null || isTimestamp(value.lastSyncedAt)) &&
    Array.isArray(value.scopes) && value.scopes.every((scope) => isOneOf(scope, scopes)));
}

function isBrokerSnapshot(value: unknown): value is BrokerSnapshot {
  return isSnapshot(value, "DEMO") &&
    Array.isArray(value.connections) && value.connections.every((row) =>
      isRecord(row) && isOneOf(row.provider, providers) && isAccount(row.account)) &&
    Array.isArray(value.events) && value.events.every((row) => isRecord(row) &&
      typeof row.id === "string" && isOneOf(row.provider, providers) && isOneOf(row.action, actions) && isTimestamp(row.at));
}

export const stagingBrokers: BrokerClient = {
  getBrokers: (options) => stagingRequest("brokers/preview", (value) => parseSnapshot(value, isBrokerSnapshot), options?.signal),
  sendBrokerAction: (provider, action, options) => stagingRequest(`brokers/preview/${provider}/actions`,
    (value) => isBrokerSnapshot(value) ? value : undefined, options?.signal, { action }),
};
