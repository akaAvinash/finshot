"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { getStagingAgentEvents, getStagingAgents, type StagingAgentEvents, type StagingAgentId } from "@/lib/api/staging-agents";
import { stagingError } from "@/lib/api/staging-client";
import { formatAgentTime } from "@/lib/agents";

type Roster = Awaited<ReturnType<typeof getStagingAgents>>;
type Result<T> = { data: T } | { error: string };
const healthLabel = { ok: "Healthy", stale: "Stale", unavailable: "Unavailable", degraded: "Degraded" } as const;
const healthReasons: Record<string, string> = {
  NO_PAPER_ACTIVITY: "No paper activity yet.",
  NOT_YET_EVALUATED: "Awaiting an advisory evaluation.",
  DATA_STALE: "The latest evaluated data is stale.",
};

export function StagingAgents() {
  const [refresh, setRefresh] = useState(0);
  const [rosterRead, setRosterRead] = useState<{ refresh: number; result: Result<Roster> }>();
  const [filter, setFilter] = useState<StagingAgentId | "">("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [eventRead, setEventRead] = useState<{ refresh: number; filter: typeof filter; cursor: typeof cursor; result: Result<StagingAgentEvents> }>();
  const roster = rosterRead?.refresh === refresh ? rosterRead.result : undefined;
  const events = eventRead?.refresh === refresh && eventRead.filter === filter && eventRead.cursor === cursor ? eventRead.result : undefined;

  useEffect(() => {
    const controller = new AbortController();
    getStagingAgents(controller.signal).then((data) => {
      if (!controller.signal.aborted) setRosterRead({ refresh, result: { data } });
    }).catch((error) => {
      if (!controller.signal.aborted) setRosterRead({ refresh, result: { error: stagingError(error, "Agent roster and health could not load.") } });
    });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    getStagingAgentEvents(filter, cursor, controller.signal).then((data) => {
      if (!controller.signal.aborted) setEventRead({ refresh, filter, cursor, result: { data } });
    }).catch((error) => {
      if (!controller.signal.aborted) setEventRead({ refresh, filter, cursor, result: { error: stagingError(error, "Advisory activity could not load.") } });
    });
    return () => controller.abort();
  }, [refresh, filter, cursor]);

  const data = roster && "data" in roster ? roster.data : undefined;
  const page = events && "data" in events ? events.data : undefined;

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Agents" description="Inspect the health and observations of the paper trading advisers."
      actions={<div className="flex flex-wrap items-center gap-2"><Status tone="accent" dot>Staging advisory</Status>
        <Button variant="outline" onClick={() => { setCursor(null); setRefresh((value) => value + 1); }}>Refresh agents</Button></div>} />
    <Card className="flex items-start gap-2 border-primary/25 bg-primary/5 p-4 text-sm">
      <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-accent-foreground" />
      <p><strong>Advisory only.</strong> Pausing advisers and acknowledging or dismissing items are unavailable in staging.</p>
    </Card>
    {!roster && <DashboardSkeleton label="Loading agents" />}
    {roster && "error" in roster && <DataState error title="Agents could not load" description={roster.error} />}
    {data && <section aria-label="Agent health" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <h2 className="font-semibold">Agent health</h2>
        <Status tone={data.health.status === "ok" ? "positive" : "accent"} dot>{healthLabel[data.health.status]}</Status>
        <time dateTime={data.health.asOf} className="text-xs text-muted-foreground">{formatAgentTime(data.health.asOf)}</time>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.agents.map((agent) => {
          const health = data.health.agents.find(({ agentId }) => agentId === agent.id);
          return <li key={agent.id} className="min-w-0"><Card className="h-full space-y-2 p-4">
            <h3 className="font-semibold">{agent.name}</h3>
            <Status tone={health?.status === "ok" ? "positive" : "neutral"} dot>{healthLabel[health?.status ?? "unavailable"]}</Status>
            <p className="text-sm text-muted-foreground">{agent.description}</p>
            {health?.reasonCode && <p className="text-xs text-muted-foreground">{healthReasons[health.reasonCode] ?? health.reasonCode}</p>}
            {health?.lastRunAt && <p className="text-xs text-muted-foreground">Last evaluated <time dateTime={health.lastRunAt}>{formatAgentTime(health.lastRunAt)}</time></p>}
          </Card></li>;
        })}
      </ul>
    </section>}
    <Card aria-labelledby="advisory-activity" className="space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="advisory-activity" className="font-semibold">Advisory activity</h2>
        {data && <div>
          <Label htmlFor="staging-agent-filter" className="sr-only">Filter advisory activity by agent</Label>
          <select id="staging-agent-filter" className="h-10 max-w-full rounded-lg border border-input bg-background px-3 text-sm" value={filter}
            onChange={({ target }) => {
              setFilter(data.agents.find(({ id }) => id === target.value)?.id ?? "");
              setCursor(null);
            }}>
            <option value="">All agents</option>
            {data.agents.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
        </div>}
      </div>
      {!events && <p role="status" className="text-sm text-muted-foreground">Loading advisory activity…</p>}
      {events && "error" in events && <p role="alert" className="text-sm text-negative">{events.error}</p>}
      {page?.items.length === 0 && <p className="text-sm text-muted-foreground">No advisory events in this view.</p>}
      {page && <ul className="space-y-2">
        {page.items.map((event) => <li key={event.id} className="space-y-2 rounded-lg border border-border p-3 wrap-anywhere">
          <div className="flex flex-wrap items-center gap-2">
            <Status tone={event.severity === "warning" ? "accent" : "neutral"}>{event.severity === "warning" ? "Warning" : "Info"}</Status>
            <span className="text-sm font-medium">{data?.agents.find(({ id }) => id === event.agentId)?.name ?? event.agentId}</span>
            <time dateTime={event.at} className="text-xs text-muted-foreground">{formatAgentTime(event.at)}</time>
          </div>
          <p className="text-sm">{event.message}</p>
          {event.recommendation && <p className="text-sm text-muted-foreground">{event.recommendation}</p>}
          <p className="text-xs text-muted-foreground">Data as of <time dateTime={event.dataAsOf}>{formatAgentTime(event.dataAsOf)}</time></p>
        </li>)}
      </ul>}
      {(cursor || page?.nextCursor) && <div className="flex flex-wrap gap-2">
        {cursor && <Button variant="outline" onClick={() => setCursor(null)}>Newest events</Button>}
        {page?.nextCursor && <Button variant="outline" onClick={() => setCursor(page.nextCursor)}>Older events</Button>}
      </div>}
    </Card>
  </div>;
}
