"use client";

import { useEffect, useState } from "react";
import { CalendarDays, Clock3 } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { useNotification } from "@/components/ui/notifications";
import { createTradeoClient } from "@/lib/api/client";
import type { PreviewScenario } from "@/lib/api/mock";
import type { DashboardResult } from "@/lib/api/types";
import { formatSnapshotDate } from "@/lib/format";
import { PortfolioCard } from "./portfolio-card";
import { PreviewControls } from "./preview-controls";
import { MarketStrip, Metrics, RecentActivity, Watchlist } from "./snapshot-cards";

type LoadState = DashboardResult | { status: "loading" } | { status: "error" };

export function Dashboard() {
  const [request, setRequest] = useState<{ scenario: PreviewScenario; notifyOnSuccess: boolean }>({
    scenario: "ready",
    notifyOnSuccess: false,
  });
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const notify = useNotification();

  useEffect(() => {
    const controller = new AbortController();

    createTradeoClient({ previewScenario: request.scenario }).getDashboard({ signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setState(result);
        if (result.status === "ready" && request.notifyOnSuccess) notify("Sample data refreshed");
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });

    return () => controller.abort();
  }, [request, notify]);

  function load(scenario: PreviewScenario, notifyOnSuccess = false) {
    setState({ status: "loading" });
    setRequest({ scenario, notifyOnSuccess });
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading
        title="Trading overview"
        description="Portfolio performance and Indian market activity in a simulated workspace."
        actions={
          <PreviewControls
            scenario={request.scenario}
            loading={state.status === "loading"}
            onScenario={load}
            onRefresh={() => load(request.scenario, true)}
          />
        }
      />
      {state.status === "loading" && <DashboardSkeleton />}
      {state.status === "empty" && (
        <DataState
          title="No sample data"
          description="This preview response has no portfolio, quotes or trades."
          action={<Button variant="outline" onClick={() => load("ready")}>Load sample data</Button>}
        />
      )}
      {state.status === "error" && (
        <DataState
          error
          title="Sample data could not load"
          description="This is a simulated request failure."
          action={<Button variant="outline" onClick={() => load("ready")}>Retry with sample data</Button>}
        />
      )}
      {(state.status === "ready" || state.status === "stale") && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <CalendarDays aria-hidden className="size-3.5" />
              Sample snapshot · <time dateTime={state.data.asOf}>{formatSnapshotDate(state.data.asOf)}</time>
            </span>
            <span>All prices in INR</span>
          </div>
          {state.status === "stale" && (
            <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/7 p-3 text-sm">
              <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Showing an older sample snapshot.</p>
              <Button size="sm" variant="outline" onClick={() => load("ready", true)}>Load latest sample</Button>
            </div>
          )}
          <MarketStrip indices={state.data.indices} />
          <Metrics data={state.data} />
          <div className="grid gap-4 min-[800px]:grid-cols-[minmax(0,1.8fr)_minmax(17.5rem,1fr)] sm:gap-5">
            <PortfolioCard points={state.data.portfolio} />
            <Watchlist quotes={state.data.watchlist} />
          </div>
          <RecentActivity trades={state.data.recentTrades} />
        </>
      )}
    </div>
  );
}
