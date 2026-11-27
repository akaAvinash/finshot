"use client";

import { useEffect, useRef, useState } from "react";
import { Clock3, LockKeyhole } from "lucide-react";
import { DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { createTradeoClient } from "@/lib/api/client";
import { canStartPaper } from "@/lib/api/auto-trading-mock";
import type { PaperCommand, PaperResult, PaperScenario } from "@/lib/api/auto-trading-types";
import { formatSnapshotDate } from "@/lib/format";
import { PaperActivity, paperTime } from "./paper-activity";
import { PaperControls } from "./paper-controls";
import { TradeControls } from "./trade-controls";
import { StagingAutoTrading } from "./staging-auto-trading";

const scenarios = [
  { value: "ready", label: "Sample data" },
  { value: "stale", label: "Stale data" },
  { value: "empty", label: "Empty workspace" },
  { value: "denied", label: "Permission denied" },
  { value: "error", label: "Request error" },
] as const;

type Request = { scenario: PaperScenario };
type Result = PaperResult | { status: "error" };

export function AutoTrading({ mode = "preview", readOnlyLimits = false }: { mode?: "preview" | "staging"; readOnlyLimits?: boolean }) {
  return mode === "staging" ? <StagingAutoTrading readOnlyLimits={readOnlyLimits} /> : <PreviewAutoTrading />;
}

function PreviewAutoTrading() {
  const [client] = useState(() => createTradeoClient());
  const [request, setRequest] = useState<Request>({ scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: Result }>();
  const [pending, setPending] = useState(false);
  const [commandError, setCommandError] = useState("");
  const command = useRef<AbortController | null>(null);
  const result = settled?.request === request ? settled.result : undefined;

  useEffect(() => {
    const controller = new AbortController();
    client.getPaperTrading({ scenario: request.scenario, signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setSettled({ request, result });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } });
      });
    return () => controller.abort();
  }, [client, request]);

  useEffect(() => () => command.current?.abort(), []);

  function load(scenario: PaperScenario) {
    if (command.current) return;
    setCommandError("");
    setRequest({ scenario });
  }

  async function run(nextCommand: PaperCommand) {
    if (command.current || result?.status !== "ready") return false;
    const controller = new AbortController();
    command.current = controller;
    setPending(true);
    setCommandError("");

    try {
      const data = await client.sendPaperCommand(nextCommand, { scenario: request.scenario, signal: controller.signal });
      if (controller.signal.aborted) return false;
      setSettled({ request, result: { status: "ready", data } });
      return true;
    } catch {
      if (!controller.signal.aborted) setCommandError("Paper controls could not be updated. Try again.");
      return false;
    } finally {
      command.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading title="Auto Trading" description="Manage paper automation, review risk checks and monitor the simulated order queue."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Status tone="accent" dot>Paper demo</Status>
            <Label htmlFor="paper-response" className="sr-only">Paper preview data</Label>
            <select id="paper-response" value={request.scenario} disabled={pending}
              onChange={({ target }) => {
                const option = scenarios.find(({ value }) => value === target.value);
                if (option) load(option.value);
              }} className="h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground">
              {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
        } />

      {!result && <Card role="status" aria-label="Loading paper workspace" className="motion-safe:animate-pulse p-6 text-sm text-muted-foreground">Loading paper workspace…</Card>}
      {result?.status === "empty" && <DataState title="No paper activity" description="This sample response contains no session, orders or trades."
        action={<Button variant="outline" onClick={() => load("ready")}>Load sample activity</Button>} />}
      {result?.status === "denied" && <DataState title="Paper workspace access denied" description="This preview simulates a session without permission to view or change paper automation."
        icon={LockKeyhole} action={<Button variant="outline" onClick={() => load("ready")}>Restore demo access</Button>} />}
      {result?.status === "error" && <DataState error title="Paper workspace could not load" description="The simulated request failed."
        action={<Button variant="outline" onClick={() => load("ready")}>Retry paper data</Button>} />}

      {(result?.status === "ready" || result?.status === "stale") && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Simulated orders and fills</span>
            <time dateTime={result.data.asOf}>Demo snapshot · {formatSnapshotDate(result.data.asOf)} · {paperTime.format(new Date(result.data.asOf))} IST</time>
          </div>
          {result.status === "stale" && (
            <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
              <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Paper data is stale. Controls are paused.</p>
              <Button variant="outline" size="sm" onClick={() => load("ready")}>Load latest paper data</Button>
            </div>
          )}
          {commandError && <p role="alert" className="text-sm text-negative">{commandError}</p>}
          {pending && <p role="status" className="sr-only">Updating paper controls</p>}
          <PaperControls snapshot={result.data} stale={result.status === "stale"} pending={pending} onRun={run} canStart={canStartPaper(result.data)} haltError={commandError} />
          <TradeControls snapshot={result.data} stale={result.status === "stale"} pending={pending} onRun={run} />
          <PaperActivity snapshot={result.data} />
        </>
      )}
    </div>
  );
}
