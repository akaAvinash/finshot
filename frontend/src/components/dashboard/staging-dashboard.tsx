"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChartNoAxesColumnIncreasing, Crosshair, RefreshCw, TrendingUp, Wallet } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { getDashboardEquity, getDashboardReport, type DashboardPaperData, type PaperEquity } from "@/lib/api/dashboard-client";
import type { PaperReport } from "@/lib/api/paper-report-types";
import { dashboardDate, dashboardLedger } from "@/lib/dashboard-ledger";
import { formatInr, formatSnapshotDate } from "@/lib/format";
import { useWatchlist } from "@/lib/market/watchlist";
import { MarketSession } from "../markets/market-summary";
import { useMarketSnapshot } from "../markets/use-market-data";
import { PortfolioChart } from "./portfolio-chart";
import { MarketStrip, MetricGrid, RecentActivity, Watchlist } from "./snapshot-cards";

type PaperLoad<T> = DashboardPaperData<T> | { status: "loading" };

export function StagingDashboard({ today: initialDate }: { today: string }) {
  const { snapshot, retry } = useMarketSnapshot("staging");
  const [report, setReport] = useState<PaperLoad<PaperReport>>({ status: "loading" });
  const [equity, setEquity] = useState<PaperLoad<PaperEquity>>({ status: "loading" });
  const [revision, setRevision] = useState(0);
  const [today, setToday] = useState(initialDate);
  const watchlist = useWatchlist();

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    void getDashboardReport(signal).then((result) => {
      if (!signal.aborted) setReport(result);
    });
    void getDashboardEquity(signal).then((result) => {
      if (!signal.aborted) setEquity(result);
    });
    return () => controller.abort();
  }, [revision]);

  function reloadPaper() {
    setReport({ status: "loading" });
    setEquity({ status: "loading" });
    setRevision((value) => value + 1);
    setToday(dashboardDate(new Date()));
  }

  const market = snapshot.status === "ready" ? snapshot.data : null;
  const instruments = market?.instruments ?? [];
  const byId = new Map(market?.overview.quotes.map((quote) => [quote.instrumentId, quote]));
  const quotes = instruments.flatMap(({ id, symbol, name, kind }) => {
    const quote = byId.get(id);
    return quote ? [{ id, symbol, name, kind, price: quote.price, changePercent: quote.changePercent }] : [];
  });
  const symbols = new Map(instruments.map(({ id, symbol }) => [id, symbol]));
  const indices = quotes.filter(({ kind }) => kind === "index");
  const savedQuotes = watchlist.flatMap((id) => {
    const quote = quotes.find((item) => item.id === id);
    return quote ? [quote] : [];
  });
  const paperReport = report.status === "ready" && report.data.reconciliation?.status !== "mismatch" ? report.data : null;
  const ledger = paperReport && dashboardLedger(paperReport, today, symbols);
  const dayPnl = ledger?.dayPnl ?? null;
  const monthPnl = ledger?.monthPnl ?? null;
  const closedTrades = paperReport?.summary.closedTrades ?? 0;
  const winningTrades = paperReport?.summary.winningTrades ?? 0;
  const loading = snapshot.status === "loading" || report.status === "loading" || equity.status === "loading";
  const missingSession = report.status === "unauthenticated" || equity.status === "unauthenticated";
  const mismatch = report.status === "ready" && report.data.reconciliation?.status === "mismatch";
  const reportFailed = report.status === "error" || mismatch;

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading title="Trading overview" description="Paper performance and Indian market activity from the staging API."
        actions={<>
          <Status tone="accent" dot>Paper demo</Status>
          <Button variant="outline" disabled={loading} onClick={() => { retry(); reloadPaper(); }}>
            <RefreshCw aria-hidden /> Refresh dashboard
          </Button>
        </>} />

      {snapshot.status === "loading" && <p role="status" className="text-sm text-muted-foreground">Loading market snapshot…</p>}
      {snapshot.status === "error" && <DataState error title="Market snapshot could not load"
        description="The market API is unavailable. Paper data can still load."
        action={<Button variant="outline" onClick={retry}>Retry market data</Button>} />}
      {market && <div className="space-y-3">
        <MarketSession overview={market.overview} />
        {indices.length > 0 ? <MarketStrip indices={indices} label={market.overview.source === "demo" ? "Backend demo market indices" : "Market indices"} />
          : <p className="text-sm text-muted-foreground">No index quotes in this market snapshot.</p>}
      </div>}

      {missingSession && <DataState error title="Paper data requires sign-in" description="Your staging session ended."
        action={<Button asChild variant="outline"><Link href="/login">Sign in again</Link></Button>} />}
      {reportFailed && <DataState error title={mismatch ? "Paper ledger could not reconcile" : "Paper ledger could not load"}
        description={mismatch ? "Ledger-derived metrics are unavailable while the balances disagree." : "The paper report API did not return an available report."}
        action={<Button variant="outline" onClick={reloadPaper}>Retry paper data</Button>} />}
      {report.status === "loading" && <DashboardSkeleton label="Loading paper ledger" />}

      <section aria-label="Paper performance" className="space-y-3">
        {paperReport && <p className="text-xs text-muted-foreground">Backend paper ledger · <time dateTime={paperReport.asOf}>{formatSnapshotDate(paperReport.asOf)}</time></p>}
        <MetricGrid metrics={[
          { label: "Paper equity", value: equity.status === "ready" ? formatInr(equity.data.equityPaise / 100) : "—", icon: Wallet,
            detail: equity.status === "ready" ? `Replay mark · ${formatSnapshotDate(equity.data.asOf)}`
              : { empty: "No paper replay yet", loading: "Loading paper account…", unauthenticated: "Sign-in required", error: "Paper account unavailable" }[equity.status] },
          { label: "Day realised P&L", value: dayPnl === null ? "—" : formatInr(dayPnl, true), pnl: dayPnl, detail: `${today} IST`, icon: TrendingUp },
          { label: "Month realised P&L", value: monthPnl === null ? "—" : formatInr(monthPnl, true), pnl: monthPnl, detail: `${today.slice(0, 7)} IST`, icon: ChartNoAxesColumnIncreasing },
          { label: "Win rate", value: closedTrades > 0 ? `${(winningTrades / closedTrades * 100).toFixed(1)}%` : "—",
            detail: closedTrades > 0 ? `${winningTrades} of ${closedTrades} closed trades` : "No closed-trade ratio available", icon: Crosshair },
        ]} />
        {equity.status === "error" && !reportFailed && <Button variant="outline" size="sm" onClick={reloadPaper}>Retry paper data</Button>}
        {report.status === "empty" && <DataState title="No paper activity yet"
          description="No paper replay or fills are available for this account."
          action={<Button asChild variant="outline"><Link href="/reports">Open Paper Reports</Link></Button>} />}
      </section>

      <div className="grid gap-4 min-[800px]:grid-cols-[minmax(0,1.8fr)_minmax(17.5rem,1fr)] sm:gap-5">
        <Card aria-labelledby="realised-pnl-heading" className="p-4 sm:p-5">
          <h2 id="realised-pnl-heading" className="font-semibold tracking-tight">Cumulative realised P&amp;L</h2>
          <p className="mt-1 text-xs text-muted-foreground">Paper fills by replay date · INR</p>
          {ledger && ledger.points.length > 0 ? <>
            <p className="mt-3 text-xl font-semibold tabular-nums">{formatInr(ledger.points.at(-1)!.value, true)}</p>
            <div className="relative mt-2 min-h-49 sm:min-h-51">
              <PortfolioChart points={ledger.points} label="Cumulative realised paper P&L chart" />
            </div>
          </> : <p className="mt-5 text-sm text-muted-foreground">No realised P&amp;L history to display.</p>}
        </Card>
        {market && <Watchlist quotes={savedQuotes} description="Saved in this browser · Market API quotes" empty="No saved instruments have quotes in this snapshot." />}
      </div>
      {ledger && <RecentActivity trades={ledger.recentTrades} paper />}
    </div>
  );
}
