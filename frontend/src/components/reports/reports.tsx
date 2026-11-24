"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock3, Download, FileText, LockKeyhole } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { createTradeoClient } from "@/lib/api/client";
import { reportPeriods, type ReportPeriod, type ReportResult, type ReportScenario, type ReportSnapshot } from "@/lib/api/report-types";
import { formatSnapshotDate } from "@/lib/format";
import { downloadReportCsv, downloadReportPdf } from "@/lib/report-download";
import { dailyReport, formatReportTime } from "@/lib/reporting";
import { ReportCalendar } from "./report-calendar";
import { ReportJournal } from "./report-journal";
import { ReportBreakdown, ReportMetrics, ReportTrend } from "./report-overview";

const periodLabels: Record<ReportPeriod, string> = { "7d": "7 days", "30d": "30 days", "90d": "90 days" };
const scenarios = [
  { value: "ready", label: "Sample data" }, { value: "stale", label: "Stale ledger" },
  { value: "empty", label: "Empty workspace" }, { value: "denied", label: "Permission denied" }, { value: "error", label: "Request error" },
] as const;

type Request = { period: ReportPeriod; scenario: ReportScenario };
type Result = ReportResult | { status: "error" };

function ReportContent({ snapshot, stale }: { snapshot: ReportSnapshot; stale: boolean }) {
  const [day, setDay] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);
  const days = useMemo(() => dailyReport(snapshot), [snapshot]);

  async function exportPdf() {
    setExporting(true);
    setExportError(false);
    try {
      await downloadReportPdf(snapshot, stale);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  }

  return <>
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
      <div className="text-xs leading-relaxed text-muted-foreground">
        <p className="text-sm font-medium text-foreground">{formatSnapshotDate(snapshot.range.from)} to {formatSnapshotDate(snapshot.range.to)} IST</p>
        <p>Demo snapshot · <time dateTime={snapshot.asOf}>{formatReportTime(snapshot.asOf)}</time></p>
      </div>
      <div className="flex flex-wrap items-center gap-2" aria-label="Export selected period">
        <Button variant="outline" className="h-11" disabled={snapshot.trades.length === 0} onClick={() => downloadReportCsv(snapshot)}><Download aria-hidden /> Export trades CSV</Button>
        <Button className="h-11" disabled={exporting} onClick={() => void exportPdf()}><FileText aria-hidden /> {exporting ? "Preparing PDF…" : "Download PDF"}</Button>
      </div>
    </div>
    {exportError && <p role="alert" className="text-sm text-negative">The demo PDF could not be created. Try again.</p>}
    <ReportMetrics snapshot={snapshot} />
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(19rem,1fr)]">
      <ReportTrend days={days} />
      <ReportCalendar days={days} range={snapshot.range} selected={day} onSelect={setDay} />
    </div>
    <ReportJournal key={day ?? "period"} trades={snapshot.trades} day={day} />
    <div className="grid gap-4 md:grid-cols-2">
      <ReportBreakdown snapshot={snapshot} field="broker" />
      <ReportBreakdown snapshot={snapshot} field="strategy" />
    </div>
  </>;
}

export function Reports() {
  const [client] = useState(() => createTradeoClient());
  const [request, setRequest] = useState<Request>({ period: "30d", scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: Result }>();
  const result = settled?.request === request ? settled.result : undefined;
  const snapshot = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;

  useEffect(() => {
    const controller = new AbortController();
    client.getReport(request.period, { scenario: request.scenario, signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setSettled({ request, result }); })
      .catch(() => { if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } }); });
    return () => controller.abort();
  }, [client, request]);

  function loadSample() {
    setRequest({ period: request.period, scenario: "ready" });
  }

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Reports" description="Review net performance, trading costs, and your simulated trade journal." actions={
      <div className="flex flex-wrap items-center gap-2">
        <Status tone="accent" dot>Demo ledger</Status>
        <Label className="sr-only" htmlFor="report-scenario">Report preview data</Label>
        <select id="report-scenario" className="h-11 rounded-lg border border-input bg-background px-3 text-sm" value={request.scenario}
          onChange={({ target }) => {
            const scenario = scenarios.find(({ value }) => value === target.value);
            if (scenario) setRequest({ period: request.period, scenario: scenario.value });
          }}>
          {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
    } />
    <div role="group" aria-label="Report period" className="flex w-fit flex-wrap items-center gap-1 rounded-lg border border-border bg-card p-0.5">
      {reportPeriods.map((period) => <Button key={period} className="h-10" variant={period === request.period ? "default" : "ghost"}
        aria-pressed={period === request.period} onClick={() => { if (period !== request.period) setRequest({ ...request, period }); }}>{periodLabels[period]}</Button>)}
    </div>
    {!result && <DashboardSkeleton label="Loading reports" />}
    {result?.status === "empty" && <DataState title="No report data" description="This demo workspace has no trades or open positions."
      action={<Button variant="outline" onClick={loadSample}>Load sample report</Button>} />}
    {result?.status === "denied" && <DataState title="Report access denied" description="This simulated session cannot view the ledger." icon={LockKeyhole}
      action={<Button variant="outline" onClick={loadSample}>Restore demo access</Button>} />}
    {result?.status === "error" && <DataState error title="Reports could not load" description="The demo ledger request failed."
      action={<Button variant="outline" onClick={loadSample}>Retry report data</Button>} />}
    {result?.status === "stale" && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
      <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Report data is stale. Current open-position marks are unavailable.</p>
      <Button variant="outline" size="sm" onClick={loadSample}>Load latest report data</Button>
    </div>}
    {snapshot && <ReportContent snapshot={snapshot} stale={result?.status === "stale"} />}
  </div>;
}
