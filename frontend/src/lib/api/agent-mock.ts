import { agentNames } from "../agents";
import { waitForMock } from "./mock-delay";
import type { AgentEvent, AgentSnapshot, AgentsClient } from "./agent-types";

function fixture(stale = false): AgentSnapshot {
  const asOf = stale ? "2026-11-23T09:53:00.000Z" : "2026-11-23T10:00:00.000Z";
  const events: AgentEvent[] = [
    { id: "event-5", agentId: "risk", at: "2026-11-23T09:59:00.000Z", severity: "critical", reason: "RISK_BLOCKED",
      message: "The paper risk policy blocked a sample intent after the daily loss threshold was reached.", review: "none" },
    { id: "event-4", agentId: "strategy", at: "2026-11-23T09:56:00.000Z", severity: "warning", reason: "SIGNAL_PROPOSED",
      message: "NIFTY Momentum v2 flagged a potential breakout. The proposal is available for advisory review.", review: "pending" },
    { id: "event-3", agentId: "execution", at: "2026-11-23T09:52:00.000Z", severity: "warning", reason: "TELEMETRY_UNAVAILABLE",
      message: "The sample replay status could not be read. No recent latency measurement is available.", review: "pending" },
    { id: "event-2", agentId: "scanner", at: "2026-11-23T09:49:00.000Z", severity: "info", reason: "MARKET_OBSERVED",
      message: "Observed higher volume in a fixed NIFTY 50 demo candle window.", review: "acknowledged" },
    { id: "event-1", agentId: "execution", at: "2026-11-23T09:45:00.000Z", severity: "info", reason: "PAPER_STATE_OBSERVED",
      message: "The monitor recorded a paper replay transition from active to paused.", review: "none" },
  ];
  return {
    source: "demo", environment: "DEMO", asOf,
    agents: [
      { id: "scanner", health: "healthy", paused: false, lastSeenAt: "2026-11-23T09:49:00.000Z", latencyMs: 124,
        failureCount: 0, decision: "Higher sample volume observed on NIFTY 50.", reason: "MARKET_OBSERVED" },
      { id: "strategy", health: "healthy", paused: false, lastSeenAt: stale ? null : "2026-11-23T09:56:00.000Z", latencyMs: stale ? null : 286,
        failureCount: stale ? null : 0, decision: stale ? "No proposal at this snapshot." : "NIFTY Momentum v2 proposal is ready for advisory review.", reason: stale ? "TELEMETRY_UNAVAILABLE" : "SIGNAL_PROPOSED" },
      { id: "risk", health: "degraded", paused: false, lastSeenAt: stale ? null : "2026-11-23T09:59:00.000Z", latencyMs: stale ? null : 540,
        failureCount: stale ? null : 2, decision: stale ? "No policy explanation at this snapshot." : "Daily loss threshold blocked a sample paper intent.", reason: stale ? "TELEMETRY_DELAYED" : "RISK_BLOCKED" },
      { id: "execution", health: "unavailable", paused: false, lastSeenAt: "2026-11-23T09:52:00.000Z", latencyMs: null,
        failureCount: null, decision: "Sample replay update unavailable.", reason: "TELEMETRY_UNAVAILABLE" },
    ],
    events: events.filter(({ at }) => at <= asOf),
  };
}

export function createAgentsMock(delay = 270): AgentsClient {
  let snapshot = fixture();
  let sequence = 0;
  return {
    async getAgents({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario === "error") throw new Error("Demo telemetry unavailable.");
      if (scenario === "denied" || scenario === "empty") return { status: scenario };
      if (scenario === "stale") return { status: "stale", data: fixture(true) };
      return { status: "ready", data: snapshot };
    },

    async sendAgentCommand(command, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario !== "ready") throw new Error("Advisory controls require current demo data.");
      const asOf = new Date(Date.parse(snapshot.asOf) + 60_000).toISOString();
      if ("agentId" in command) {
        const agent = snapshot.agents.find(({ id }) => id === command.agentId);
        if (!agent) throw new Error("Demo observer unavailable.");
        const paused = command.kind === "pause";
        if (agent.paused === paused) throw new Error("Demo observer already has that state.");
        const event: AgentEvent = {
          id: `operator-${++sequence}`, agentId: agent.id, at: asOf, severity: "info", review: "none",
          reason: paused ? "OBSERVER_PAUSED" : "OBSERVER_RESUMED",
          message: `${agentNames[agent.id]} was ${paused ? "paused" : "resumed"} for this demo visit.`,
        };
        snapshot = { ...snapshot, asOf, agents: snapshot.agents.map((item) => item.id === agent.id ? { ...item, paused } : item), events: [event, ...snapshot.events] };
      } else {
        const target = snapshot.events.find(({ id }) => id === command.eventId);
        if (target?.review !== "pending") throw new Error("This advisory item is no longer awaiting review.");
        const review = command.kind === "acknowledge" ? "acknowledged" : "dismissed";
        snapshot = { ...snapshot, asOf, events: snapshot.events.map((event) => event.id === target.id ? { ...event, review } : event) };
      }
      return snapshot;
    },
  };
}
