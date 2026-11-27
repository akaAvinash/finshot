"use client";

import { useEffect, useRef, useState } from "react";
import { CircleAlert, Clock3, Link2, LockKeyhole, Unplug } from "lucide-react";
import { DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { createTradeoClient } from "@/lib/api/client";
import type { BrokerAction, BrokerId, BrokerResult, BrokerScenario, BrokerStatus } from "@/lib/api/broker-types";
import { brokerNames, formatBrokerTime, getBrokerStatus } from "@/lib/brokers";
import { cn } from "@/lib/utils";
import { BrokerActivity } from "./broker-activity";
import { BrokerCard } from "./broker-card";

const scenarios = [
  { value: "ready", label: "Sample data" },
  { value: "stale", label: "Stale data" },
  { value: "empty", label: "Empty workspace" },
  { value: "denied", label: "Permission denied" },
  { value: "error", label: "Request error" },
] as const;

const filters = [
  { value: "all", label: "All brokers" },
  { value: "connected", label: "Connected" },
  { value: "expired", label: "Session expired" },
  { value: "disconnected", label: "Disconnected" },
] as const;
const summaries = [
  { status: "connected", label: "Connected", icon: Link2, tone: "text-positive" },
  { status: "expired", label: "Expired", icon: CircleAlert, tone: "text-accent-foreground" },
  { status: "disconnected", label: "Disconnected", icon: Unplug, tone: "text-muted-foreground" },
] as const;
const actionLabel: Record<BrokerAction, string> = {
  connect: "demo account connected",
  reconnect: "demo session reconnected",
  sync: "demo account synced",
  disconnect: "demo account disconnected",
};

type Request = { scenario: BrokerScenario };
type Result = BrokerResult | { status: "error"; message: string };

export function Brokers() {
  const [client] = useState(() => createTradeoClient());
  const [request, setRequest] = useState<Request>({ scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: Result }>();
  const [filter, setFilter] = useState<"all" | BrokerStatus>("all");
  const [pending, setPending] = useState<BrokerId | null>(null);
  const [actionError, setActionError] = useState<{ provider: BrokerId; action: BrokerAction; message: string }>();
  const command = useRef<AbortController | null>(null);
  const notify = useNotification();
  const result = settled?.request === request ? settled.result : undefined;

  useEffect(() => {
    const controller = new AbortController();
    client.getBrokers({ scenario: request.scenario, signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setSettled({ request, result });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSettled({ request, result: { status: "error", message: "The simulated broker request failed." } });
      });
    return () => controller.abort();
  }, [client, request]);

  useEffect(() => () => command.current?.abort(), []);

  function load(scenario: BrokerScenario) {
    if (command.current) return;
    setActionError(undefined);
    setRequest({ scenario });
  }

  async function run(provider: BrokerId, action: BrokerAction) {
    if (command.current || result?.status !== "ready") return false;
    const controller = new AbortController();
    command.current = controller;
    setPending(provider);
    setActionError(undefined);

    try {
      const data = await client.sendBrokerAction(provider, action, { scenario: request.scenario, signal: controller.signal });
      if (controller.signal.aborted) return false;
      setSettled({ request, result: { status: "ready", data } });
      if (action !== "sync") setFilter("all");
      notify(`${brokerNames[provider]} ${actionLabel[action]}`);
      return true;
    } catch {
      const fallback = action === "sync" ? "Demo account sync failed. Try again." : "The demo action did not complete. Try again.";
      if (!controller.signal.aborted) setActionError({ provider, action, message: fallback });
      return false;
    } finally {
      command.current = null;
      if (!controller.signal.aborted) setPending(null);
    }
  }

  const snapshot = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;
  const entries = snapshot?.connections.map((connection) => ({
    connection,
    status: getBrokerStatus(connection.account, snapshot.asOf),
  })) ?? [];
  const visible = filter === "all" ? entries : entries.filter(({ status }) => status === filter);

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading title="Brokers" description="Manage sample connections, check session health and review account syncs." actions={
        <div className="flex flex-wrap items-center gap-2">
          <Status tone="accent" dot>Demo connections</Status>
          <Label htmlFor="broker-response" className="sr-only">Broker preview data</Label>
          <select id="broker-response" value={request.scenario} disabled={pending !== null}
            onChange={({ target }) => {
              const scenario = scenarios.find(({ value }) => value === target.value);
              if (scenario) load(scenario.value);
            }} className="h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground">
            {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      } />

      {!result && <Card role="status" aria-label="Loading brokers" className="motion-safe:animate-pulse p-6 text-sm text-muted-foreground">Loading demo brokers…</Card>}
      {result?.status === "empty" && <DataState title="No broker connections to display" description="This sample response contains no broker accounts."
        action={<Button variant="outline" onClick={() => load("ready")}>Load sample brokers</Button>} />}
      {result?.status === "denied" && <DataState title="Broker access denied" description="This preview simulates a session without permission to view broker accounts."
        icon={LockKeyhole} action={<Button variant="outline" onClick={() => load("ready")}>Restore demo access</Button>} />}
      {result?.status === "error" && <DataState error title="Brokers could not load" description={result.message}
        action={<Button variant="outline" onClick={() => load("ready")}>Retry broker data</Button>} />}

      {snapshot && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Simulated, read-only broker access</span>
            <time dateTime={snapshot.asOf}>Demo snapshot · {formatBrokerTime(snapshot.asOf)}</time>
          </div>
          {result?.status === "stale" && (
            <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
              <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Broker data is stale. Account actions are paused.</p>
              <Button variant="outline" size="sm" onClick={() => load("ready")}>Load latest broker data</Button>
            </div>
          )}
          <dl aria-label="Demo connection summary" className="grid grid-cols-3 gap-2 sm:gap-4">
            {summaries.map(({ status, label, icon: Icon, tone }) => (
              <div key={status} className="min-w-0 rounded-xl border border-border bg-card px-2.5 py-3.5 sm:px-4">
                <dt className="flex flex-col items-start gap-1.5 text-xs font-medium text-muted-foreground sm:flex-row sm:items-center sm:text-sm">
                  <Icon aria-hidden className={cn("size-4 shrink-0", tone)} />
                  {label}
                </dt>
                <dd className="mt-1.5 text-2xl font-semibold tracking-tight tabular-nums">{entries.filter((entry) => entry.status === status).length}</dd>
              </div>
            ))}
          </dl>

          <section aria-labelledby="broker-connections-heading" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="broker-connections-heading" className="text-sm font-semibold">Broker connections</h2>
              <Label htmlFor="broker-status-filter" className="sr-only">Filter broker connections</Label>
              <select id="broker-status-filter" value={filter} disabled={pending !== null}
                onChange={({ target }) => {
                  const next = filters.find(({ value }) => value === target.value);
                  if (next) setFilter(next.value);
                }} className="h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground">
                {filters.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
              </select>
            </div>
            {actionError?.action === "sync" && <p role="alert" className="text-sm text-negative">{actionError.message}</p>}
            {pending && <p role="status" className="sr-only">Updating {brokerNames[pending]} demo connection</p>}
            {visible.length ? (
              <div className="grid gap-4 min-[760px]:grid-cols-2">
                {visible.map(({ connection }) => (
                  <BrokerCard key={connection.provider} connection={connection} asOf={snapshot.asOf}
                    disabled={result?.status === "stale" || pending !== null} pending={pending === connection.provider} onAction={run}
                    actionError={actionError?.provider === connection.provider ? actionError : undefined} />
                ))}
              </div>
            ) : (
              <DataState title="No brokers match this filter" description="Select another status to see your demo connections."
                action={<Button variant="outline" onClick={() => setFilter("all")}>Show all brokers</Button>} />
            )}
          </section>
          <BrokerActivity events={snapshot.events} />
        </>
      )}
    </div>
  );
}
