import { Clock3, FileSearch } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { agentIds, agentSeverities, type AgentEvent } from "@/lib/api/agent-types";
import { agentNames, formatAgentTime, reasonLabels, severityLabels } from "@/lib/agents";
import { cn } from "@/lib/utils";

const tones = { info: "neutral", warning: "accent", critical: "negative" } as const;
const dots = { info: "bg-muted-foreground", warning: "bg-primary", critical: "bg-negative" } as const;
const reviewed = { pending: "Awaiting review", acknowledged: "Acknowledged", dismissed: "Dismissed" } as const;
const selectClass = "h-11 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground sm:px-3";

export function AgentTimeline({ events, disabled, onReview }: {
  events: readonly AgentEvent[];
  disabled: boolean;
  onReview: (event: AgentEvent, opener: HTMLButtonElement) => void;
}) {
  const [agent, setAgent] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [pendingOnly, setPendingOnly] = useState(false);
  const visible = events.filter((event) => (agent === "all" || agent === event.agentId) &&
    (severity === "all" || severity === event.severity) && (!pendingOnly || event.review === "pending"));

  return <Card aria-labelledby="agent-timeline" className="overflow-hidden">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 sm:px-5">
      <div>
        <h2 id="agent-timeline" tabIndex={-1} className="flex items-center gap-2 font-semibold"><Clock3 aria-hidden className="size-4 text-accent-foreground" /> Advisory timeline</h2>
        <p className="mt-1 text-xs text-muted-foreground">{visible.length} demo events · Newest first</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="agent-timeline-filter" className="sr-only">Filter events by agent</Label>
        <select id="agent-timeline-filter" className={selectClass} value={agent} onChange={({ target }) => setAgent(target.value)}>
          <option value="all">All agents</option>{agentIds.map((id) => <option key={id} value={id}>{agentNames[id]}</option>)}
        </select>
        <Label htmlFor="agent-severity-filter" className="sr-only">Filter events by severity</Label>
        <select id="agent-severity-filter" className={selectClass} value={severity} onChange={({ target }) => setSeverity(target.value)}>
          <option value="all">Any severity</option>{agentSeverities.map((value) => <option key={value} value={value}>{severityLabels[value]}</option>)}
        </select>
        <Button variant={pendingOnly ? "default" : "outline"} className="h-11" aria-pressed={pendingOnly} onClick={() => setPendingOnly(!pendingOnly)}>Awaiting review</Button>
      </div>
    </header>
    {visible.length ? <ol className="divide-y divide-border">
      {visible.map((event) => <li key={event.id} className="grid gap-2.5 px-4 py-3.5 sm:grid-cols-[8.5rem_minmax(0,1fr)_auto] sm:items-start sm:px-5">
        <div className="flex items-center gap-2 text-xs tabular-nums text-muted-foreground">
          <span aria-hidden className={cn("size-2 shrink-0 rounded-full", dots[event.severity])} />
          <time dateTime={event.at}>{formatAgentTime(event.at)}</time>
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="text-sm font-semibold">{reasonLabels[event.reason]}</h3>
            <span className="text-xs text-muted-foreground">{agentNames[event.agentId]}</span>
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{event.message}</p>
          <code className="mt-1 block text-xs wrap-anywhere text-muted-foreground">{event.reason}</code>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <Status tone={tones[event.severity]}>{severityLabels[event.severity]}</Status>
          {event.review === "pending" ? <Button variant="outline" className="h-10" disabled={disabled}
            aria-label={`Review ${reasonLabels[event.reason]}`} onClick={(input) => onReview(event, input.currentTarget)}><FileSearch aria-hidden /> Review</Button>
            : event.review !== "none" && <Status>{reviewed[event.review]}</Status>}
        </div>
      </li>)}
    </ol> : <p className="p-5 text-sm text-muted-foreground">No advisory events match this view.</p>}
  </Card>;
}
