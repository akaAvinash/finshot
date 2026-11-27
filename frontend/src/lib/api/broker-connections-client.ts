import { hasStrings, isOneOf, isRecord, isSnapshot, isTimestamp, stagingRequest } from "./staging-client";

export const brokerCallbackPath = "/brokers/callback";
const root = "broker-connections";
const capabilityNames = ["profile_read", "holdings_read", "positions_read", "orders_read", "funds_read"] as const;
type Capability = (typeof capabilityNames)[number];
export type BrokerProvider = {
  id: string; displayName: string; environment: "DEMO"; capabilities: Capability[]; maxConnections: number; available: boolean;
};
export type BrokerConnection = {
  connectionId: string; providerId: string; status: "connected" | "expired"; statusReason: "EXPIRED" | "AUTH_INVALIDATED" | null;
  maskedAccountId: string; capabilities: Capability[]; connectedAt: string; expiresAt: string; lastSyncedAt: string | null;
};
type BrokerEvent = { id: string; connectionId: string; providerId: string; action: "connect" | "reconnect" | "sync" | "disconnect" | "expire"; at: string };
export type BrokerConnectionsSnapshot = {
  source: "demo"; environment: "DEMO"; asOf: string; providers: BrokerProvider[]; connections: BrokerConnection[]; events: BrokerEvent[];
};
export type BrokerAuthorizationStart = { providerId: string } | { connectionId: string };
type Authorization = { authorizationId: string; providerId: string; authorizeUrl: string; expiresAt: string };
export type BrokerCallback = { state: string; params: Record<string, string> };
type InstrumentRef = { instrumentId: string | null; providerSymbol: string };
type Holding = { instrument: InstrumentRef; quantity: string; averagePrice: string; lastPrice: string | null };
type Position = { instrument: InstrumentRef; product: string; quantity: string; averagePrice: string; realisedPnl: string; unrealisedPnl: string };
type Order = { providerOrderId: string; instrument: InstrumentRef; side: string; orderType: string; quantity: string; filledQuantity: string; price: string | null; status: string; placedAt: string };
type Funds = { available: string; used: string; total: string };
export type BrokerPortfolio = { connectionId: string; asOf: string | null; holdings: Holding[] | null; positions: Position[] | null; orders: Order[] | null; funds: Funds | null };

const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const providerId = (value: unknown): value is string => typeof value === "string" && /^[a-z][a-z0-9_-]{1,31}$/.test(value);
const capabilities = (value: unknown): value is Capability[] => Array.isArray(value) && value.every((item) => isOneOf(item, capabilityNames));
const nullableDate = (value: unknown): value is string | null => value === null || isTimestamp(value);
const decimal = (value: unknown): value is string => typeof value === "string" && /^-?[0-9]{1,15}(\.[0-9]{1,6})?$/.test(value);

function provider(value: unknown): value is BrokerProvider {
  return isRecord(value) && providerId(value.id) && typeof value.displayName === "string" && value.displayName.length > 0 &&
    value.environment === "DEMO" && capabilities(value.capabilities) && typeof value.maxConnections === "number" &&
    Number.isSafeInteger(value.maxConnections) && value.maxConnections > 0 && typeof value.available === "boolean";
}

function connection(value: unknown): value is BrokerConnection {
  return isRecord(value) && uuid(value.connectionId) && providerId(value.providerId) && isOneOf(value.status, ["connected", "expired"]) &&
    (value.statusReason === null || isOneOf(value.statusReason, ["EXPIRED", "AUTH_INVALIDATED"])) &&
    typeof value.maskedAccountId === "string" && /^•••• [A-Za-z0-9]{2,6}$/.test(value.maskedAccountId) &&
    capabilities(value.capabilities) && isTimestamp(value.connectedAt) && isTimestamp(value.expiresAt) && nullableDate(value.lastSyncedAt);
}

function event(value: unknown): value is BrokerEvent {
  return isRecord(value) && typeof value.id === "string" && uuid(value.connectionId) && providerId(value.providerId) &&
    isOneOf(value.action, ["connect", "reconnect", "sync", "disconnect", "expire"]) && isTimestamp(value.at);
}

function snapshot(value: unknown): BrokerConnectionsSnapshot | undefined {
  if (isSnapshot(value, "DEMO") && Array.isArray(value.providers) && value.providers.every(provider) &&
      Array.isArray(value.connections) && value.connections.every(connection) && Array.isArray(value.events) && value.events.every(event) &&
      isTimestamp(value.asOf)) {
    return { source: "demo", environment: "DEMO", asOf: value.asOf, providers: value.providers, connections: value.connections, events: value.events };
  }
}

function authorization(value: unknown): Authorization | undefined {
  if (isRecord(value) && uuid(value.authorizationId) && providerId(value.providerId) &&
    typeof value.authorizeUrl === "string" && isTimestamp(value.expiresAt)) {
    return { authorizationId: value.authorizationId, providerId: value.providerId, authorizeUrl: value.authorizeUrl, expiresAt: value.expiresAt };
  }
}

function instrument(value: unknown): value is InstrumentRef {
  return isRecord(value) && typeof value.providerSymbol === "string" &&
    (value.instrumentId === null || typeof value.instrumentId === "string");
}

function holding(value: unknown): value is Holding {
  return isRecord(value) && instrument(value.instrument) && decimal(value.quantity) && decimal(value.averagePrice) &&
    (value.lastPrice === null || decimal(value.lastPrice));
}

function position(value: unknown): value is Position {
  return isRecord(value) && instrument(value.instrument) && isOneOf(value.product, ["intraday", "delivery", "other"]) &&
    ["quantity", "averagePrice", "realisedPnl", "unrealisedPnl"].every((key) => decimal(value[key]));
}

function order(value: unknown): value is Order {
  return isRecord(value) && instrument(value.instrument) && hasStrings(value, ["providerOrderId", "side", "orderType", "status"]) &&
    decimal(value.quantity) && decimal(value.filledQuantity) && (value.price === null || decimal(value.price)) && isTimestamp(value.placedAt);
}

function funds(value: unknown): value is Funds {
  return isRecord(value) && decimal(value.available) && decimal(value.used) && decimal(value.total);
}

function list<T>(value: unknown, guard: (value: unknown) => value is T): value is T[] | null {
  return value === null || (Array.isArray(value) && value.every(guard));
}

export function demoAuthorizationPath(value: string, origin: string) {
  try {
    const url = new URL(value, origin);
    if (url.origin === origin && url.pathname === brokerCallbackPath && !url.username && !url.password && !url.hash &&
        parseBrokerCallback(url.searchParams)) return url.pathname + url.search;
  } catch {}
}

export function parseBrokerCallback(query: URLSearchParams): BrokerCallback | undefined {
  const state = query.get("state");
  if (!state || state.length < 16 || state.length > 256 || query.getAll("state").length !== 1) return;
  const params = [...query.entries()].filter(([name]) => name !== "state");
  if (params.length > 10 || new Set(params.map(([name]) => name)).size !== params.length ||
      params.some(([, value]) => value.length > 512)) return;
  return { state, params: Object.fromEntries(params) };
}

export const getBrokerConnections = (signal?: AbortSignal) => stagingRequest(root, snapshot, signal);
export const startBrokerAuthorization = (payload: BrokerAuthorizationStart, signal?: AbortSignal) =>
  stagingRequest(`${root}/authorizations`, authorization, signal, payload);
export const completeBrokerAuthorization = (payload: BrokerCallback, signal?: AbortSignal) =>
  stagingRequest(`${root}/authorizations/callback`, (value) => {
    if (!isRecord(value) || !uuid(value.connectionId)) return;
    const data = snapshot(value.snapshot);
    if (data && data.connections.some(({ connectionId }) => connectionId === value.connectionId)) return data;
  }, signal, payload);
export const sendBrokerConnectionAction = (id: string, action: "sync" | "disconnect", signal?: AbortSignal) =>
  stagingRequest(`${root}/${encodeURIComponent(id)}/actions`, snapshot, signal, { action });
export const getBrokerPortfolio = (id: string, signal?: AbortSignal) =>
  stagingRequest<BrokerPortfolio>(`${root}/${encodeURIComponent(id)}/portfolio`, (value) => {
    if (isRecord(value) && value.source === "demo" && value.environment === "DEMO" && value.connectionId === id &&
        nullableDate(value.asOf) && list(value.holdings, holding) && list(value.positions, position) &&
        list(value.orders, order) && (value.funds === null || funds(value.funds))) {
      return { connectionId: id, asOf: value.asOf, holdings: value.holdings, positions: value.positions, orders: value.orders, funds: value.funds };
    }
  }, signal);
