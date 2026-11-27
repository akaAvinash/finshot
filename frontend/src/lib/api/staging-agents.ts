import { hasStrings, isOneOf, isRecord, isSnapshot, isTimestamp, stagingRequest } from "./staging-client";

const agentIds = ["market-scanner", "strategy-analyst", "risk-explainer", "execution-monitor"] as const;
export type StagingAgentId = (typeof agentIds)[number];
type Agent = { id: StagingAgentId; name: string; description: string };
type AgentHealth = {
  agentId: StagingAgentId; status: "ok" | "stale" | "unavailable"; reasonCode: string | null; lastRunAt: string | null;
};
type HealthReport = { asOf: string; status: "ok" | "degraded" | "unavailable"; agents: AgentHealth[] };
type AgentEvent = {
  id: string; agentId: StagingAgentId; at: string; dataAsOf: string; severity: "info" | "warning";
  reasonCode: string; message: string; recommendation: string | null;
};
export type StagingAgentEvents = { items: AgentEvent[]; nextCursor: string | null };

function isPaperDemo(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && value.source === "demo" && value.environment === "PAPER";
}

function isRoster(value: unknown): value is { agents: Agent[] } {
  return isPaperDemo(value) && Array.isArray(value.agents) && value.agents.every((row) => isRecord(row) &&
    isOneOf(row.id, agentIds) && hasStrings(row, ["name", "description"]) && row.role === "advisory");
}

function isHealth(value: unknown): value is HealthReport {
  return isSnapshot(value, "PAPER") && isOneOf(value.status, ["ok", "degraded", "unavailable"]) &&
    Array.isArray(value.agents) && value.agents.every((row) => isRecord(row) &&
      isOneOf(row.agentId, agentIds) && isOneOf(row.status, ["ok", "stale", "unavailable"]) &&
      (row.reasonCode === null || typeof row.reasonCode === "string") &&
      (row.lastRunAt === null || isTimestamp(row.lastRunAt)));
}

function isEvents(value: unknown): value is StagingAgentEvents {
  return isPaperDemo(value) && (value.nextCursor === null || typeof value.nextCursor === "string") &&
    Array.isArray(value.items) && value.items.every((row) => isRecord(row) && isOneOf(row.agentId, agentIds) &&
      hasStrings(row, ["id", "reasonCode", "message"]) && isTimestamp(row.at) && isTimestamp(row.dataAsOf) &&
      isOneOf(row.severity, ["info", "warning"]) && (row.recommendation === null || typeof row.recommendation === "string"));
}

export async function getStagingAgents(signal?: AbortSignal) {
  const [roster, health] = await Promise.all([
    stagingRequest("agents", (value) => isRoster(value) ? value : undefined, signal),
    stagingRequest("agents/health", (value) => isHealth(value) ? value : undefined, signal),
  ]);
  return { agents: roster.agents, health };
}

export function getStagingAgentEvents(agentId: StagingAgentId | "", cursor: string | null, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: "25" });
  if (agentId) query.set("agentId", agentId);
  if (cursor) query.set("cursor", cursor);
  return stagingRequest(`agents/events?${query}`, (value) => isEvents(value) ? value : undefined, signal);
}
