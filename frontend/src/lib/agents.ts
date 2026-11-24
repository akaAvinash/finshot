import type { AgentId, AgentReason, AgentSeverity } from "./api/agent-types";

export const agentNames = {
  scanner: "Market Scanner", strategy: "Strategy Analyst", risk: "Risk Explainer", execution: "Execution Monitor",
} as const satisfies Record<AgentId, string>;

export const agentRoles = {
  scanner: "Summarizes price movement in the demo market snapshot.",
  strategy: "Records sample proposals for human review.",
  risk: "Explains outcomes from the deterministic risk policy.",
  execution: "Reads paper replay events and reports their status.",
} as const satisfies Record<AgentId, string>;

export const reasonLabels = {
  MARKET_OBSERVED: "Market observation", SIGNAL_PROPOSED: "Signal proposed", RISK_BLOCKED: "Risk limit applied",
  PAPER_STATE_OBSERVED: "Paper state observed", TELEMETRY_DELAYED: "Telemetry delayed", TELEMETRY_UNAVAILABLE: "Telemetry unavailable",
  OBSERVER_PAUSED: "Observer paused", OBSERVER_RESUMED: "Observer resumed",
} as const satisfies Record<AgentReason, string>;

export const severityLabels = { info: "Info", warning: "Warning", critical: "Critical" } as const satisfies Record<AgentSeverity, string>;

const time = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function formatAgentTime(value: string) {
  return `${time.format(new Date(value))} IST`;
}
