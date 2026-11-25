import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { ReportActivity, RetryReport } from "@/components/reports/report-activity";
import { ReportExport } from "@/components/reports/report-export";
import { CurrentReplay, ReportMetrics, StrategyBreakdown } from "@/components/reports/report-overview";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { samplePaperReport } from "@/lib/api/paper-report-preview";
import { readPaperReport, type PaperReportResponse } from "@/lib/api/paper-report-server";
import { readAuthConfig } from "@/lib/auth/config";
import { sessionCookie } from "@/lib/auth/upstream";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";
import { formatSnapshotDate } from "@/lib/format";
import { formatReportTime, parseReportPeriod, reportQuery } from "@/lib/paper-reporting";

export const metadata: Metadata = { title: "Reports" };

export default async function ReportsPage({ searchParams }: { searchParams: Promise<{ from?: string | string[]; to?: string | string[] }> }) {
  const { mode } = await requireWorkspaceSession();
  const { from, to } = await searchParams;
  const { period, error } = parseReportPeriod(from, to);
  let result: PaperReportResponse;
  if (error) result = { status: "invalid" };
  else if (mode === "preview") result = samplePaperReport(period);
  else {
    const config = readAuthConfig();
    const token = (await cookies()).get(sessionCookie)?.value;
    if (!token) redirect("/login");
    result = config.mode === "staging" ? await readPaperReport(config.upstream, token, period) : { status: "unavailable" };
  }

  if (result.status === "unauthenticated") redirect("/login");

  return <div className="min-w-0 space-y-4 sm:space-y-5">
    <PageHeading title="Reports" description="Paper trading performance, daily P&L and fill history." actions={
      <Status tone="accent" dot>{mode === "preview" ? "Sample data" : "Paper trading"}</Status>
    } />

    <Card className="flex flex-wrap items-end justify-between gap-3 p-3.5 sm:p-4" aria-label="Report period">
      <form action="/reports" method="get" className="grid w-full grid-cols-2 items-end gap-2 sm:flex sm:w-auto sm:flex-wrap">
        <div className="min-w-0 space-y-1.5">
          <Label htmlFor="report-from" className="block">From date</Label>
          <Input id="report-from" name="from" type="date" defaultValue={period.from ?? ""} className="h-11 w-full min-w-0 sm:w-41" />
        </div>
        <div className="min-w-0 space-y-1.5">
          <Label htmlFor="report-to" className="block">To date</Label>
          <Input id="report-to" name="to" type="date" defaultValue={period.to ?? ""} className="h-11 w-full min-w-0 sm:w-41" />
        </div>
        <Button type="submit" variant="outline" className="h-11">Apply dates</Button>
        {(from || to) && <Button asChild variant="ghost" className="h-11"><Link href="/reports">All dates</Link></Button>}
      </form>
      {result.status === "ready" && <ReportExport key={reportQuery(period)} period={period} />}
    </Card>

    {result.status === "invalid" && <DataState error title="Check the report dates" description={error ?? "The report date range was rejected."} />}
    {result.status === "unavailable" && <DataState error title="Paper report unavailable" description="The paper ledger could not be loaded." action={<RetryReport />} />}
    {result.status === "empty" && <DataState title="No paper report yet" description="This account has no assigned paper replay or recorded fills." />}

    {result.status === "ready" && <>
      <div className="flex flex-wrap justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
        <p>{result.data.period.from ? formatSnapshotDate(result.data.period.from) : "Any start date"} · {result.data.period.to ? formatSnapshotDate(result.data.period.to) : "Any end date"} (IST)</p>
        <p>As of <time dateTime={result.data.asOf}>{formatSnapshotDate(result.data.asOf)} · {formatReportTime(result.data.asOf)} IST</time></p>
      </div>
      <ReportMetrics summary={result.data.summary} />
      <ReportActivity key={reportQuery(period)} days={result.data.daily} journal={result.data.journal} truncated={result.data.journalTruncated} />
      <div className="grid items-start gap-4 md:grid-cols-2">
        <StrategyBreakdown rows={result.data.strategies} />
        <CurrentReplay position={result.data.openPosition} reconciliation={result.data.reconciliation} />
      </div>
    </>}
  </div>;
}
