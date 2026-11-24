export type BrokerId = "zerodha" | "fyers";
export type BrokerScope = "profile_read" | "holdings_read" | "orders_read";
export type BrokerStatus = "connected" | "expired" | "disconnected";
export type BrokerAction = "connect" | "reconnect" | "sync" | "disconnect";
export type BrokerScenario = "ready" | "stale" | "empty" | "denied" | "error";

export type BrokerAccount = Readonly<{
  maskedAccountId: string;
  connectedAt: string;
  expiresAt: string;
  lastSyncedAt: string | null;
  scopes: readonly BrokerScope[];
}>;

export type BrokerConnection = Readonly<{
  provider: BrokerId;
  account: BrokerAccount | null;
}>;

export type BrokerEvent = Readonly<{
  id: string;
  provider: BrokerId;
  action: BrokerAction;
  at: string;
}>;

export type BrokerSnapshot = Readonly<{
  source: "demo";
  environment: "DEMO";
  asOf: string;
  connections: readonly BrokerConnection[];
  events: readonly BrokerEvent[];
}>;

export type BrokerResult =
  | { status: "ready" | "stale"; data: BrokerSnapshot }
  | { status: "empty" | "denied" };

type BrokerRequestOptions = { scenario?: BrokerScenario; signal?: AbortSignal };

export interface BrokerClient {
  getBrokers(options?: BrokerRequestOptions): Promise<BrokerResult>;
  sendBrokerAction(provider: BrokerId, action: BrokerAction, options?: BrokerRequestOptions): Promise<BrokerSnapshot>;
}
