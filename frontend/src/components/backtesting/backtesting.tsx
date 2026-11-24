"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Clock3, ListOrdered, LockKeyhole } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import type { BacktestConfig, BacktestRun, BacktestScenario, BacktestWorkspace, BacktestWorkspaceResult } from "@/lib/api/backtest-types";
import { createTradeoClient } from "@/lib/api/client";
import { BacktestInputError, formatBacktestTime } from "@/lib/backtesting";
import { formatSnapshotDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BacktestForm } from "./backtest-form";
import { BacktestResults } from "./backtest-results";

const scenarios = [
  { value: "ready", label: "Sample data" }, { value: "stale", label: "Stale snapshot" },
  { value: "empty", label: "No sample history" }, { value: "denied", label: "Permission denied" },
  { value: "error", label: "Request error" }, { value: "run-error", label: "Worker failure" },
] as const;

const runStatus = {
  queued: { label: "Queued", tone: "accent" }, running: { label: "Running", tone: "accent" },
  completed: { label: "Completed", tone: "positive" }, failed: { label: "Failed", tone: "negative" },
} as const;

type Request = { scenario: BacktestScenario };
type Result = BacktestWorkspaceResult | { status: "error" };

function RunQueue({ workspace, selectedId, onSelect }: {
  workspace: BacktestWorkspace;
  selectedId: string | undefined;
  onSelect: (id: string) => void;
}) {
  return (
    <Card aria-labelledby="backtest-queue" className="p-4 sm:p-5">
      <h2 id="backtest-queue" className="flex items-center gap-2 font-semibold"><ListOrdered aria-hidden className="size-4 text-accent-foreground" /> Run queue</h2>
      {workspace.runs.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No demo runs queued.</p> : (
        <ul className="mt-3 max-h-76 space-y-2 overflow-y-auto p-1">
          {workspace.runs.map((run) => {
            const strategy = workspace.strategies.find(({ id }) => id === run.config.strategyId);
            const copy = runStatus[run.status];
            const selected = selectedId === run.id;
            return <li key={run.id}>
              <button type="button" aria-pressed={selected} onClick={() => onSelect(run.id)}
                className={cn("flex w-full items-start justify-between gap-2 rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-surface-raised",
                  selected && "border-primary/35 bg-primary/7")}>
                <span className="min-w-0"><span className="block truncate text-sm font-medium">{strategy?.name ?? "Demo backtest"}</span>
                  <time dateTime={run.queuedAt} className="mt-1 block text-xs leading-relaxed text-muted-foreground">{formatBacktestTime(run.queuedAt)}</time>
                </span>
                <Status tone={copy.tone} dot>{copy.label}</Status>
              </button>
            </li>;
          })}
        </ul>
      )}
    </Card>
  );
}

export function Backtesting() {
  const [client] = useState(() => createTradeoClient());
  const [request, setRequest] = useState<Request>({ scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: Result }>();
  const [selected, setSelected] = useState<string>();
  const [activeRun, setActiveRun] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [pollError, setPollError] = useState(false);
  const [pollAttempt, setPollAttempt] = useState(0);
  const submission = useRef<AbortController | null>(null);
  const notify = useNotification();
  const result = settled?.request === request ? settled.result : undefined;
  const workspace = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;
  const selectedRun = workspace?.runs.find(({ id }) => id === selected) ?? workspace?.runs[0];
  const busy = submitting || activeRun !== undefined;

  useEffect(() => {
    const controller = new AbortController();
    client.getBacktestWorkspace({ scenario: request.scenario, signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setSettled({ request, result });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } });
      });
    return () => controller.abort();
  }, [client, request]);

  useEffect(() => () => submission.current?.abort(), []);

  const updateRun = useCallback((run: BacktestRun) => {
    setSettled((previous) => {
      if (!previous || previous.request !== request || previous.result.status !== "ready") return previous;
      const data = previous.result.data;
      return { request, result: { status: "ready", data: { ...data, asOf: run.asOf, runs: [run, ...data.runs.filter(({ id }) => id !== run.id)] } } };
    });
  }, [request]);

  useEffect(() => {
    if (activeRun === undefined) return;
    const id = activeRun;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const run = await client.getBacktestRun(id, { signal: controller.signal });
        if (controller.signal.aborted) return;
        updateRun(run);
        if (run.status === "queued" || run.status === "running") timer = setTimeout(poll, 250);
        else {
          setActiveRun(undefined);
          if (run.status === "completed") notify("Demo backtest completed");
        }
      } catch {
        if (!controller.signal.aborted) setPollError(true);
      }
    }

    timer = setTimeout(poll, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [activeRun, client, notify, pollAttempt, updateRun]);

  function load(scenario: BacktestScenario) {
    if (busy) return;
    setRequest({ scenario });
    setSelected(undefined);
    setSubmitError(null);
  }

  async function start(config: BacktestConfig) {
    if (submission.current || busy || result?.status !== "ready") return;
    const controller = new AbortController();
    submission.current = controller;
    setSubmitting(true);
    setSubmitError(null);

    try {
      const run = await client.startBacktest(config, { scenario: request.scenario, signal: controller.signal });
      if (controller.signal.aborted) return;
      updateRun(run);
      setSelected(run.id);
      if (run.status === "queued" || run.status === "running") setActiveRun(run.id);
    } catch (error) {
      if (!controller.signal.aborted) setSubmitError(error instanceof BacktestInputError ? error.message : "The demo run could not be queued. Try again.");
    } finally {
      submission.current = null;
      if (!controller.signal.aborted) setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading title="Backtesting" description="Replay a strategy setup on demo history and inspect holdout performance." actions={
        <div className="flex flex-wrap items-center gap-2">
          <Status tone="accent" dot>Demo only</Status>
          <Label className="sr-only" htmlFor="backtest-scenario">Backtest preview data</Label>
          <select id="backtest-scenario" className="h-11 rounded-lg border border-input bg-background px-3 text-sm" value={request.scenario} disabled={busy}
            onChange={({ target }) => {
              const scenario = scenarios.find(({ value }) => value === target.value);
              if (scenario) load(scenario.value);
            }}>
            {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      } />
      {!result && <DashboardSkeleton label="Loading backtests" />}
      {result?.status === "denied" && <DataState title="Backtest access denied" description="This demo session has no access to the workspace." icon={LockKeyhole}
        action={<Button variant="outline" onClick={() => load("ready")}>Restore demo access</Button>} />}
      {result?.status === "error" && <DataState error title="Backtesting could not load" description="The simulated workspace request failed."
        action={<Button variant="outline" onClick={() => load("ready")}>Retry backtest data</Button>} />}

      {workspace && <>
        <p className="border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">Sample snapshot · <time dateTime={workspace.asOf}>{formatSnapshotDate(workspace.asOf)} IST</time> · Daily demo candles · Shared sample rule</p>
        {result?.status === "stale" && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
          <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Backtest data is stale. New runs are paused.</p>
          <Button variant="outline" size="sm" onClick={() => load("ready")}>Load latest backtest data</Button>
        </div>}
        <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[19rem_minmax(0,1fr)] xl:gap-5">
          <div className="min-w-0 space-y-4">
            <BacktestForm workspace={workspace} canRun={result?.status === "ready"} busy={busy} onRun={start} />
            {submitError && <p role="alert" className="rounded-lg border border-negative/30 bg-negative/8 p-3 text-sm text-negative">{submitError}</p>}
            <RunQueue workspace={workspace} selectedId={selectedRun?.id} onSelect={setSelected} />
          </div>
          <section aria-label="Selected backtest results" className="min-w-0 space-y-4">
            {pollError && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-negative/30 p-3 text-sm">
              <p>Run status could not refresh.</p>
              <Button variant="outline" size="sm" onClick={() => { setPollError(false); setPollAttempt((attempt) => attempt + 1); }}>Retry run status</Button>
            </div>}
            <BacktestResults run={selectedRun} workspace={workspace} />
          </section>
        </div>
      </>}
    </div>
  );
}
