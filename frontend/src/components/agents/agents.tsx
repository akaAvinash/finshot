"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, CircleAlert, Clock3, FileSearch, LockKeyhole, ShieldCheck } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { agentNames, formatAgentTime, reasonLabels } from "@/lib/agents";
import type { AgentCommand, AgentEvent, AgentResult, AgentScenario } from "@/lib/api/agent-types";
import { createTradeoClient } from "@/lib/api/client";
import { AgentRoster } from "./agent-roster";
import { AgentTimeline } from "./agent-timeline";

const scenarios = [
  { value: "ready", label: "Sample data" }, { value: "stale", label: "Stale telemetry" },
  { value: "empty", label: "Empty workspace" }, { value: "denied", label: "Permission denied" }, { value: "error", label: "Request error" },
] as const;
const messages = { pause: "Demo observer paused", resume: "Demo observer resumed", acknowledge: "Advisory item acknowledged", dismiss: "Advisory item dismissed" } as const;

type Request = { scenario: AgentScenario };
type Result = AgentResult | { status: "error" };

export function Agents() {
  const [client] = useState(() => createTradeoClient());
  const [request, setRequest] = useState<Request>({ scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: Result }>();
  const [review, setReview] = useState<AgentEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [commandError, setCommandError] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const notify = useNotification();
  const result = settled?.request === request ? settled.result : undefined;
  const snapshot = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;
  const controlsDisabled = result?.status !== "ready" || busy;

  useEffect(() => {
    const controller = new AbortController();
    client.getAgents({ scenario: request.scenario, signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setSettled({ request, result }); })
      .catch(() => { if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } }); });
    return () => controller.abort();
  }, [client, request]);

  useEffect(() => () => pending.current?.abort(), []);

  function load(scenario: AgentScenario) {
    if (pending.current) return;
    setCommandError(false);
    setRequest({ scenario });
  }

  async function run(command: AgentCommand) {
    if (pending.current || result?.status !== "ready") return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setCommandError(false);
    try {
      const data = await client.sendAgentCommand(command, { scenario: request.scenario, signal: controller.signal });
      if (controller.signal.aborted) return;
      setSettled({ request, result: { status: "ready", data } });
      if ("eventId" in command) setReview(null);
      notify(messages[command.kind]);
    } catch {
      if (!controller.signal.aborted) setCommandError(true);
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const counts = snapshot && [
    { label: "Healthy observers", icon: Activity, value: snapshot.agents.filter((agent) => !agent.paused && agent.health === "healthy").length },
    { label: "Needs attention", icon: CircleAlert, value: snapshot.agents.filter((agent) => !agent.paused && agent.health !== "healthy").length },
    { label: "Awaiting review", icon: FileSearch, value: snapshot.events.filter((event) => event.review === "pending").length },
  ];

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Agents" description="Inspect agent health, recent observations, and advisory items for review." actions={
      <div className="flex flex-wrap items-center gap-2">
        <Status tone="accent" dot>Demo advisory</Status>
        <Label htmlFor="agent-scenario" className="sr-only">Agent preview data</Label>
        <select id="agent-scenario" className="h-11 rounded-lg border border-input bg-background px-3 text-sm" value={request.scenario} disabled={busy}
          onChange={({ target }) => {
            const scenario = scenarios.find(({ value }) => value === target.value);
            if (scenario) load(scenario.value);
          }}>
          {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
    } />

    {!result && <DashboardSkeleton label="Loading agents" />}
    {result?.status === "empty" && <DataState title="No agent activity" description="This demo workspace has no agent roster or advisory events."
      action={<Button variant="outline" onClick={() => load("ready")}>Load sample agents</Button>} />}
    {result?.status === "denied" && <DataState title="Agent access denied" description="This simulated session cannot view advisory telemetry." icon={LockKeyhole}
      action={<Button variant="outline" onClick={() => load("ready")}>Restore demo access</Button>} />}
    {result?.status === "error" && <DataState error title="Agents could not load" description="The demo telemetry request failed."
      action={<Button variant="outline" onClick={() => load("ready")}>Retry agent data</Button>} />}

    {snapshot && <>
      <Card className="flex flex-wrap items-center justify-between gap-3 border-primary/25 bg-primary/5 px-4 py-3.5">
        <div className="flex max-w-2xl items-start gap-2">
          <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-accent-foreground" />
          <p className="text-sm leading-relaxed"><strong className="font-semibold">Advisory only.</strong> The risk policy decides whether paper orders are eligible. Reviews here only record that a demo item was seen or dismissed.</p>
        </div>
        <p className="text-xs text-muted-foreground">Sample snapshot · <time dateTime={snapshot.asOf}>{formatAgentTime(snapshot.asOf)}</time></p>
      </Card>
      {result?.status === "stale" && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
        <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Agent telemetry is stale. Advisory controls are paused.</p>
        <Button variant="outline" size="sm" onClick={() => load("ready")}>Load latest agent data</Button>
      </div>}
      <dl className="grid grid-cols-3 gap-2.5" aria-label="Demo advisory summary">
        {counts?.map(({ label, value, icon: Icon }) => <div key={label} className="min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4">
          <dt className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground sm:flex-row sm:items-center"><Icon aria-hidden className="size-4 shrink-0 text-accent-foreground" />{label}</dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
        </div>)}
      </dl>
      {commandError && !review && <p role="alert" className="text-sm text-negative">The demo action did not complete. Try again.</p>}
      <AgentRoster agents={snapshot.agents} disabled={controlsDisabled} onToggle={(agent) => void run({ kind: agent.paused ? "resume" : "pause", agentId: agent.id })} />
      <AgentTimeline events={snapshot.events} disabled={controlsDisabled} onReview={(event, button) => {
        opener.current = button;
        setCommandError(false);
        setReview(event);
      }} />
    </>}

    <Dialog open={review !== null} onOpenChange={(open) => {
      if (!open && !pending.current) { setReview(null); setCommandError(false); }
    }}>
      {review && <DialogContent onCloseAutoFocus={(event) => {
        event.preventDefault();
        if (opener.current?.isConnected && !opener.current.disabled) opener.current.focus();
        else document.getElementById("agent-timeline")?.focus();
      }}>
        <DialogTitle>Review {reasonLabels[review.reason].toLowerCase()}</DialogTitle>
        <DialogDescription>Record a decision about this demo advisory item. Neither action authorizes an order or changes a risk limit.</DialogDescription>
        <div className="mt-4 rounded-lg border border-border bg-background/55 p-3 text-sm leading-relaxed">
          <p className="font-medium">{agentNames[review.agentId]}</p><p className="mt-1 text-muted-foreground">{review.message}</p>
        </div>
        {commandError && <p role="alert" className="mt-3 text-sm text-negative">The demo action did not complete. Try again.</p>}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button variant="outline" className="h-11" disabled={controlsDisabled} onClick={() => void run({ kind: "dismiss", eventId: review.id })}>Dismiss item</Button>
          <Button className="h-11" disabled={controlsDisabled} onClick={() => void run({ kind: "acknowledge", eventId: review.id })}>Acknowledge</Button>
        </div>
      </DialogContent>}
    </Dialog>
  </div>;
}
