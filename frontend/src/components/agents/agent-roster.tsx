import { Activity, Layers, Pause, Play, Radar, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import type { AgentStatus } from "@/lib/api/agent-types";
import { agentNames, agentRoles, formatAgentTime, reasonLabels } from "@/lib/agents";

const icons = { scanner: Radar, strategy: Layers, risk: ShieldCheck, execution: Activity } as const;
const stateLabels = {
  healthy: { label: "Healthy", tone: "positive" }, degraded: { label: "Degraded", tone: "accent" },
  unavailable: { label: "Unavailable", tone: "negative" }, paused: { label: "Paused", tone: "neutral" },
} as const;

export function AgentRoster({ agents, disabled, onToggle }: {
  agents: readonly AgentStatus[];
  disabled: boolean;
  onToggle: (agent: AgentStatus) => void;
}) {
  return <section aria-labelledby="agents-roster" className="space-y-3">
    <h2 id="agents-roster" className="text-sm font-semibold">Agent roster</h2>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {agents.map((agent) => {
        const { id, paused, latencyMs, failureCount, lastSeenAt } = agent;
        const Icon = icons[id];
        const status = stateLabels[paused ? "paused" : agent.health];
        return <Card key={id} aria-labelledby={`agent-${id}`} className="flex flex-col p-4 sm:p-5">
          <div className="flex items-start justify-between gap-2">
            <span className="grid size-10 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-accent-foreground"><Icon aria-hidden className="size-5" /></span>
            <Status tone={status.tone} dot>{status.label}</Status>
          </div>
          <h3 id={`agent-${id}`} className="mt-3 text-lg font-semibold tracking-tight">{agentNames[id]}</h3>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{agentRoles[id]}</p>
          <div className="mt-4 flex-1 rounded-lg border border-border bg-background/45 p-3">
            <p className="text-xs font-medium text-accent-foreground">{reasonLabels[agent.reason]}</p>
            <p className="mt-1 text-sm leading-relaxed">{agent.decision}</p>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-2 gap-y-3 tabular-nums">
            <div><dt className="text-xs text-muted-foreground">Last latency</dt><dd className="mt-1 text-sm font-medium">{latencyMs === null ? "Unavailable" : `${latencyMs} ms`}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Sample failures</dt><dd className="mt-1 text-sm font-medium">{failureCount ?? "Unavailable"}</dd></div>
            <div className="col-span-2"><dt className="text-xs text-muted-foreground">Last observation</dt><dd className="mt-1 text-sm font-medium">
              {lastSeenAt ? <time dateTime={lastSeenAt}>{formatAgentTime(lastSeenAt)}</time> : "Unavailable"}
            </dd></div>
          </dl>
          <Button variant="outline" className="mt-4 h-11 w-full" disabled={disabled} aria-label={`${paused ? "Resume" : "Pause"} ${agentNames[id]}`} onClick={() => onToggle(agent)}>
            {paused ? <Play aria-hidden /> : <Pause aria-hidden />} {paused ? "Resume demo" : "Pause demo"}
          </Button>
        </Card>;
      })}
    </div>
  </section>;
}
