"use client";

import { useEffect, useRef, useState } from "react";
import { Clock3, LayoutGrid, List, LockKeyhole, Plus, Search } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { createTradeoClient } from "@/lib/api/client";
import { strategyRiskTiers, type Strategy, type StrategyCommand, type StrategyResult, type StrategyScenario } from "@/lib/api/strategy-types";
import { formatSnapshotDate } from "@/lib/format";
import { listedStrategyRevision, riskLabels, strategyCandidate, strategyStatusLabels } from "@/lib/strategies";
import { cn } from "@/lib/utils";
import { StrategyDetails } from "./strategy-details";
import { StrategyEditor, strategySelectClass } from "./strategy-editor";
import { StrategyCard, StrategySummary, StrategyTable } from "./strategy-list";

const scenarios = [
  { value: "ready", label: "Sample data" }, { value: "stale", label: "Stale data" },
  { value: "empty", label: "Empty workspace" }, { value: "denied", label: "Permission denied" },
  { value: "error", label: "Request error" },
] as const;
const messages = { create: "Demo draft created", "save-draft": "Demo draft saved", activate: "Demo strategy activated", pause: "Demo strategy paused" } as const;

type Request = { scenario: StrategyScenario };
type Result = StrategyResult | { status: "error" };
type Panel = { mode: "create" } | { mode: "details" | "edit"; id: string };

export function Strategies() {
  const [client] = useState(() => createTradeoClient());
  const [request, setRequest] = useState<Request>({ scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: Result }>();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [risk, setRisk] = useState("all");
  const [view, setView] = useState<"cards" | "table">("cards");
  const [panel, setPanel] = useState<Panel | null>(null);
  const [busy, setBusy] = useState(false);
  const [commandError, setCommandError] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const returnFocus = useRef<HTMLButtonElement>(null);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const notify = useNotification();
  const result = settled?.request === request ? settled.result : undefined;
  const canWrite = result?.status === "ready";
  const snapshot = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;

  useEffect(() => {
    const controller = new AbortController();
    client.getStrategies({ scenario: request.scenario, signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setSettled({ request, result });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } });
      });
    return () => controller.abort();
  }, [client, request]);

  useEffect(() => () => pending.current?.abort(), []);

  function open(next: Panel, opener: HTMLButtonElement) {
    returnFocus.current = opener;
    setCommandError(false);
    setPanel(next);
  }

  function resetFilters() {
    setQuery("");
    setStatus("all");
    setRisk("all");
  }

  async function run(command: StrategyCommand) {
    if (pending.current || !canWrite) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setCommandError(false);

    try {
      const data = await client.sendStrategyCommand(command, { scenario: request.scenario, signal: controller.signal });
      if (controller.signal.aborted) return;
      setSettled({ request, result: { status: "ready", data } });
      if (command.action === "create") {
        resetFilters();
        setPanel(null);
      } else {
        setPanel({ mode: "details", id: command.id });
      }
      notify(messages[command.action]);
    } catch {
      if (!controller.signal.aborted) setCommandError(true);
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const needle = query.trim().toLowerCase();
  const visible = snapshot?.strategies.filter((strategy) => {
    const parameters = listedStrategyRevision(strategy)?.parameters;
    return parameters && (status === "all" || status === strategy.status) && (risk === "all" || risk === parameters.riskTier) &&
      `${parameters.name} ${parameters.instrument} ${parameters.description}`.toLowerCase().includes(needle);
  }) ?? [];
  const selected = panel && panel.mode !== "create" ? snapshot?.strategies.find(({ id }) => id === panel.id) : undefined;
  const selectedParameters = selected && strategyCandidate(selected)?.parameters;

  function openDetails(strategy: Strategy, opener: HTMLButtonElement) {
    open({ mode: "details", id: strategy.id }, opener);
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading title="Strategies" description="Review sample performance, manage drafts, and check deployment eligibility." actions={
        <Button className="h-11" disabled={!canWrite || busy} onClick={(event) => open({ mode: "create" }, event.currentTarget)}><Plus aria-hidden /> Create strategy</Button>
      } />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-2"><Status tone="accent" dot>Demo strategies</Status>
          {snapshot && <time dateTime={snapshot.asOf}>Sample snapshot · {formatSnapshotDate(snapshot.asOf)} IST</time>}
        </div>
        <Label className="sr-only" htmlFor="strategy-scenario">Strategy preview data</Label>
        <select id="strategy-scenario" className={cn(strategySelectClass, "w-auto")} value={request.scenario} disabled={busy} onChange={({ target }) => {
          const scenario = scenarios.find(({ value }) => value === target.value);
          if (scenario) setRequest({ scenario: scenario.value });
        }}>
          {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>

      {!result && <DashboardSkeleton label="Loading strategies" />}
      {result?.status === "empty" && <DataState title="No strategies to display" description="This sample workspace contains no strategies."
        action={<Button variant="outline" onClick={() => setRequest({ scenario: "ready" })}>Load sample strategies</Button>} />}
      {result?.status === "denied" && <DataState title="Strategy access denied" description="This scenario simulates a session without permission to view strategies." icon={LockKeyhole}
        action={<Button variant="outline" onClick={() => setRequest({ scenario: "ready" })}>Restore demo access</Button>} />}
      {result?.status === "error" && <DataState error title="Strategies could not load" description="The simulated request failed."
        action={<Button variant="outline" onClick={() => setRequest({ scenario: "ready" })}>Retry strategy data</Button>} />}

      {snapshot && <>
        {result?.status === "stale" && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
          <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Strategy data is stale. Editing and activation are paused.</p>
          <Button variant="outline" size="sm" onClick={() => setRequest({ scenario: "ready" })}>Load latest strategy data</Button>
        </div>}
        <StrategySummary strategies={snapshot.strategies} />
        <section aria-labelledby="strategy-library" className="space-y-3">
          <h2 id="strategy-library" ref={resultsHeading} tabIndex={-1} className="text-sm font-semibold">Strategy library</h2>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 w-full sm:w-auto sm:flex-1">
              <Label className="sr-only" htmlFor="strategy-search">Search strategies</Label>
              <Search aria-hidden className="pointer-events-none absolute top-3.5 left-3 size-4 text-muted-foreground" />
              <Input id="strategy-search" type="search" className="pl-9" placeholder="Search by name or instrument" value={query} onChange={({ target }) => setQuery(target.value)} />
            </div>
            <div className="grid min-w-0 flex-1 grid-cols-2 gap-2 sm:flex sm:flex-[0_0_auto]">
              <Label className="sr-only" htmlFor="strategy-status-filter">Filter strategies by status</Label>
              <select id="strategy-status-filter" className={cn(strategySelectClass, "sm:w-32")} value={status} onChange={({ target }) => setStatus(target.value)}>
                <option value="all">Any status</option>
                {Object.entries(strategyStatusLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
              </select>
              <Label className="sr-only" htmlFor="strategy-risk-filter">Filter strategies by risk</Label>
              <select id="strategy-risk-filter" className={cn(strategySelectClass, "sm:w-32")} value={risk} onChange={({ target }) => setRisk(target.value)}>
                <option value="all">Any risk</option>
                {strategyRiskTiers.map((value) => <option key={value} value={value}>{riskLabels[value]}</option>)}
              </select>
            </div>
            <div role="group" aria-label="Strategy layout" className="flex shrink-0 items-center gap-1 rounded-lg border border-border bg-card p-0.5">
              <Button size="icon" variant={view === "cards" ? "default" : "ghost"} aria-label="Card view" aria-pressed={view === "cards"} onClick={() => setView("cards")}><LayoutGrid aria-hidden /></Button>
              <Button size="icon" variant={view === "table" ? "default" : "ghost"} aria-label="Table view" aria-pressed={view === "table"} onClick={() => setView("table")}><List aria-hidden /></Button>
            </div>
          </div>
          {visible.length === 0 ? <DataState title="No strategies match" description="Change the search or clear your filters."
            action={<Button variant="outline" onClick={resetFilters}>Clear filters</Button>} /> : view === "cards" ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {visible.map((strategy) => <StrategyCard key={strategy.id} strategy={strategy} onOpen={openDetails} />)}
            </div>
          ) : <StrategyTable strategies={visible} onOpen={openDetails} />}
        </section>
      </>}

      <Dialog open={panel !== null} onOpenChange={(open) => { if (!open && !pending.current) setPanel(null); }}>
        {panel && (
          <DialogContent className="max-w-xl" onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (returnFocus.current?.isConnected && !returnFocus.current.disabled) returnFocus.current.focus();
            else resultsHeading.current?.focus();
          }}>
            {panel.mode === "details" && selected ? (
              <StrategyDetails strategy={selected} canWrite={canWrite} busy={busy} onEdit={() => {
                setCommandError(false);
                setPanel({ mode: "edit", id: selected.id });
              }} onAction={(action) => void run({ action, id: selected.id })} />
            ) : (
              <StrategyEditor initial={panel.mode === "edit" ? selectedParameters : undefined} busy={busy}
                onCancel={() => {
                  setCommandError(false);
                  setPanel(panel.mode === "edit" ? { mode: "details", id: panel.id } : null);
                }} onSave={(parameters) => panel.mode === "create" ? run({ action: "create", parameters }) : run({ action: "save-draft", id: panel.id, parameters })} />
            )}
            {commandError && <p role="alert" className="mt-3 text-sm text-negative">The demo change did not complete. Try again.</p>}
            {busy && <p role="status" className="sr-only">Updating demo strategy</p>}
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}
