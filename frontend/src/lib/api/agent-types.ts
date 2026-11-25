export const agentIds = ["scanner", "strategy", "risk", "execution"] as const;
export const agentSeverities = ["info", "warning", "critical"] as const;

export type AgentId = (typeof agentIds)[number];
export type AgentSeverity = (typeof agentSeverities)[number];
export type AgentScenario = "ready" | "stale" | "empty" | "denied" | "error";
export type AgentHealth = "healthy" | "degraded" | "unavailable";
export type AgentReason = "MARKET_OBSERVED" | "SIGNAL_PROPOSED" | "RISK_BLOCKED" | "PAPER_STATE_OBSERVED" | "TELEMETRY_DELAYED" | "TELEMETRY_UNAVAILABLE" | "OBSERVER_PAUSED" | "OBSERVER_RESUMED";

export type AgentStatus = {
  id: AgentId;
  health: AgentHealth;
  paused: boolean;
  lastSeenAt: string | null;
  latencyMs: number | null;
  failureCount: number | null;
  decision: string;
  reason: AgentReason;
};

export type AgentEvent = {
  id: string;
  agentId: AgentId;
  at: string;
  severity: AgentSeverity;
  reason: AgentReason;
  message: string;
  review: "none" | "pending" | "acknowledged" | "dismissed";
};

export type AgentSnapshot = {
  source: "demo";
  environment: "DEMO";
  asOf: string;
  agents: readonly AgentStatus[];
  events: readonly AgentEvent[];
};

export type AgentResult = { status: "ready" | "stale"; data: AgentSnapshot } | { status: "empty" | "denied" };
export type AgentCommand =
  | { kind: "pause" | "resume"; agentId: AgentId }
  | { kind: "acknowledge" | "dismiss"; eventId: string };

type AgentRequestOptions = { scenario?: AgentScenario; signal?: AbortSignal };

export interface AgentsClient {
  getAgents(options?: AgentRequestOptions): Promise<AgentResult>;
  sendAgentCommand(command: AgentCommand, options?: AgentRequestOptions): Promise<AgentSnapshot>;
}
