import { randomUUID } from "node:crypto";

const asOf = "2026-11-23T10:00:00Z";
const capabilities = ["profile_read", "holdings_read", "funds_read"];
const provider = { id: "sample-broker", displayName: "Sample Broker", environment: "DEMO", capabilities, maxConnections: 2, available: true };
const defaults = {
  lossLimitPaise: 180000, tradeLimit: 8, profitLimitPaise: null, maxConsecutiveLosses: 0,
  stopLossBps: null, takeProfitBps: null, maxRiskPerTradePaise: 75000, maxPositionSizeBps: 10000,
};
const bounds = Object.fromEntries(Object.entries({
  lossLimitPaise: 180000, tradeLimit: 8, profitLimitPaise: 100000000, maxConsecutiveLosses: 8,
  stopLossBps: 9999, takeProfitBps: 10000, maxRiskPerTradePaise: 75000, maxPositionSizeBps: 10000,
}).map(([field, maximum]) => [field, { minimum: field === "maxConsecutiveLosses" ? 0 : 1, maximum, nullable: defaults[field] === null }]));
const failure = (status, code, message, extra) => [status, { code, message, ...extra }];
const stepUp = () => failure(403, "STEP_UP_REQUIRED", "Verify with your authenticator.");
const snapshot = (row) => ({ source: "demo", environment: "DEMO", asOf, providers: [provider], connections: row.connections, events: row.events });

export function createContractWorkspaceFixture() {
  const accounts = new Map();
  let rejectAction = false;
  function rowFor(owner) {
    if (!accounts.has(owner)) accounts.set(owner, {
      settings: { environment: "PAPER", revision: 0, updatedAt: null, controls: { ...defaults }, defaults, bounds },
      changes: [], connections: [], events: [], authorizations: new Map(),
    });
    return accounts.get(owner);
  }

  function handle(path, owner, body, steppedUp, engine) {
    const row = rowFor(owner);
    if (path === "settings/trade-controls/history") return [200, { changes: row.changes }];
    if (path === "settings/trade-controls") {
      if (body === undefined) return [200, row.settings];
      if (!steppedUp) return stepUp();
      if (engine === "running") return failure(409, "TRADE_CONTROLS_ENGINE_RUNNING", "Pause the paper engine before saving.");
      if (body.expectedRevision !== row.settings.revision) return failure(409, "TRADE_CONTROLS_REVISION_CONFLICT", "The saved limits have changed. Load the latest revision.");
      const fieldErrors = Object.entries(bounds).flatMap(([field, bound]) => {
        const value = body.controls?.[field];
        return (value === null ? bound.nullable : Number.isInteger(value) && value >= bound.minimum && value <= bound.maximum) ? [] : [{ field, bound }];
      });
      if (fieldErrors.length) return failure(400, "TRADE_CONTROLS_OUT_OF_BOUNDS", "One or more limits are out of bounds.", { fieldErrors });
      const fields = Object.keys(defaults).filter((field) => row.settings.controls[field] !== body.controls[field])
        .map((field) => ({ field, from: row.settings.controls[field], to: body.controls[field] }));
      if (fields.length) {
        row.settings = { ...row.settings, controls: body.controls, revision: row.settings.revision + 1, updatedAt: asOf };
        row.changes.unshift({ revision: row.settings.revision, changedAt: asOf, fields });
      }
      return [200, row.settings];
    }
    if (path === "broker-connections") return [200, snapshot(row)];
    if (path === "broker-connections/authorizations") {
      if (!steppedUp) return stepUp();
      const connection = row.connections.find(({ connectionId }) => connectionId === body.connectionId);
      if (body.connectionId ? !connection : body.providerId !== provider.id) return failure(404, "BROKER_CONNECTION_NOT_FOUND", "The connection could not be found.");
      if (!connection && row.connections.length >= provider.maxConnections) return failure(409, "BROKER_CONNECTION_LIMIT", "The provider connection limit was reached.");
      const authorizationId = randomUUID();
      const state = randomUUID();
      row.authorizations.set(state, body.connectionId ?? null);
      return [201, {
        authorizationId, providerId: provider.id, authorizeUrl: `/brokers/callback?state=${state}&code=demo`,
        expiresAt: new Date(Date.now() + 60_000).toISOString(),
      }];
    }
    if (path === "broker-connections/authorizations/callback") {
      if (!row.authorizations.has(body.state) || body.params?.code !== "demo") return failure(400, "BROKER_AUTHORIZATION_INVALID", "The demo authorization is invalid.");
      const previous = row.authorizations.get(body.state);
      row.authorizations.delete(body.state);
      const connectionId = previous ?? randomUUID();
      const connection = {
        connectionId, providerId: provider.id, status: "connected", statusReason: null, maskedAccountId: "•••• 0248", capabilities,
        connectedAt: asOf, expiresAt: "2026-12-01T10:00:00Z", lastSyncedAt: null,
      };
      if (previous) row.connections = row.connections.map((entry) => entry.connectionId === previous ? connection : entry);
      else row.connections.push(connection);
      row.events.push({ id: randomUUID(), connectionId, providerId: provider.id, action: previous ? "reconnect" : "connect", at: asOf });
      return [200, { connectionId, snapshot: snapshot(row) }];
    }
    const connectionPath = /^broker-connections\/([^/]+)\/(actions|portfolio)$/.exec(path);
    if (!connectionPath) return;
    const [, connectionId, operation] = connectionPath;
    const connection = row.connections.find((entry) => entry.connectionId === connectionId);
    if (!connection) return failure(404, "BROKER_CONNECTION_NOT_FOUND", "The connection could not be found.");
    if (operation === "portfolio") {
      return [200, { source: "demo", environment: "DEMO", connectionId, asOf: connection.lastSyncedAt, holdings: connection.lastSyncedAt ?
        [{ instrument: { instrumentId: "NSE:SBIN", providerSymbol: "SBIN" }, quantity: "10", averagePrice: "532.12", lastPrice: "535.123456" }] : [],
        positions: null, orders: null, funds: connection.lastSyncedAt ? { available: "7000.25", used: "3000.75", total: "10001.00" } : null }];
    }
    if (rejectAction) {
      rejectAction = false;
      return failure(409, "BROKER_ACTION_CONFLICT", "The broker connection changed. Refresh before trying again.");
    }
    if (body.action === "sync") connection.lastSyncedAt = asOf;
    else if (body.action === "disconnect") row.connections = row.connections.filter((entry) => entry.connectionId !== connectionId);
    else return failure(400, "INVALID_REQUEST", "Unsupported broker action.");
    row.events.push({ id: randomUUID(), connectionId, providerId: provider.id, action: body.action, at: asOf });
    return [200, snapshot(row)];
  }
  return { handle, settings: (owner) => rowFor(owner).settings, rejectNextAction: () => { rejectAction = true; } };
}
