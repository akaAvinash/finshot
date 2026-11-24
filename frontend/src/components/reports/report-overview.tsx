import { Activity, ChartNoAxesCombined, Layers, Plug, Receipt, Wallet } from "lucide-react";
import { PortfolioChart } from "@/components/dashboard/portfolio-chart";
import { Card } from "@/components/ui/card";
import type { ReportSnapshot } from "@/lib/api/report-types";
import { formatInr } from "@/lib/format";
import { dailyReport, reportBreakdown, summarizeReport } from "@/lib/reporting";
import { cn } from "@/lib/utils";

function money(value: number | null, signed = true) {
  return value === null ? "Unavailable" : formatInr(value / 100, signed);
}

export function ReportMetrics({ snapshot }: { snapshot: ReportSnapshot }) {
  const totals = summarizeReport(snapshot);
  const metrics = [
    { label: "Net P&L", value: totals.netPaise, note: "Net realized + marked open P&L", icon: Wallet },
    { label: "Net realized", value: totals.realizedPaise, note: `Gross ${money(totals.grossPaise)} before charges`, icon: ChartNoAxesCombined },
    { label: "Unrealized P&L", value: totals.unrealizedPaise, note: snapshot.marks === null ? "Open position marks unavailable" : `${snapshot.marks.length} open positions at snapshot`, icon: Activity },
    { label: "Charges & taxes", value: totals.chargesPaise, note: `${money(totals.brokeragePaise, false)} brokerage · ${money(totals.taxesPaise, false)} taxes`, icon: Receipt, cost: true },
  ];

  return <dl className="grid grid-cols-2 gap-2.5 xl:grid-cols-4" aria-label="Demo report metrics">
    {metrics.map(({ label, value, note, icon: Icon, cost }) => <div key={label} className="min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4">
      <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Icon aria-hidden className="size-4 shrink-0 text-accent-foreground" />{label}</dt>
      <dd className={cn("mt-2 text-xl font-semibold tracking-tight wrap-anywhere tabular-nums",
        value === null && "text-muted-foreground", !cost && value !== null && (value > 0 ? "text-positive" : value < 0 ? "text-negative" : "text-foreground"))}>{money(value, !cost)}</dd>
      <dd className="mt-1 text-xs leading-relaxed text-muted-foreground">{note}</dd>
    </div>)}
  </dl>;
}

const formatAxisValue = (value: number) => formatInr(value);

export function ReportTrend({ days }: { days: ReturnType<typeof dailyReport> }) {
  const points = days.map(({ date, cumulativePaise }) => ({ date, value: cumulativePaise / 100 }));
  return <Card className="overflow-hidden" aria-labelledby="report-trend-heading">
    <div className="border-b border-border p-4 sm:px-5">
      <h2 id="report-trend-heading" className="flex items-center gap-2 font-semibold"><Activity aria-hidden className="size-4 text-accent-foreground" /> Realized P&L trend</h2>
      <p className="mt-1 text-xs text-muted-foreground">Cumulative closed-trade P&L after brokerage and taxes.</p>
    </div>
    <div className="relative mx-3 my-3 h-59 sm:mx-4 sm:h-70">
      <PortfolioChart points={points} label="Demo cumulative realized P&L chart" formatValue={formatAxisValue} />
    </div>
  </Card>;
}

export function ReportBreakdown({ snapshot, field }: { snapshot: ReportSnapshot; field: "broker" | "strategy" }) {
  const rows = reportBreakdown(snapshot.trades, field);
  const max = Math.max(1, ...rows.map(({ netPaise }) => Math.abs(netPaise)));
  const Icon = field === "broker" ? Plug : Layers;
  const heading = `report-${field}-breakdown`;
  return <Card aria-labelledby={heading} className="p-4 sm:p-5">
    <h2 id={heading} className="flex items-center gap-2 font-semibold"><Icon aria-hidden className="size-4 text-accent-foreground" /> {field === "broker" ? "By broker" : "By strategy"}</h2>
    <p className="mt-1 text-xs text-muted-foreground">Net realized P&L for the selected period.</p>
    {rows.length === 0 ? <p className="mt-4 text-sm text-muted-foreground">No closed trades to group.</p> : <ul className="mt-3 divide-y divide-border">
      {rows.map(({ label, netPaise, trades }) => <li key={label} className="space-y-2 py-2.5 last:pb-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
          <span className="font-medium wrap-anywhere">{label} <span className="text-xs font-normal text-muted-foreground">· {trades} closed</span></span>
          <span className={cn("font-semibold tabular-nums", netPaise > 0 && "text-positive", netPaise < 0 && "text-negative")}>{money(netPaise)}</span>
        </div>
        <div aria-hidden className="h-1.5 overflow-hidden rounded-full bg-surface-raised">
          <div className={cn("h-full rounded-full", netPaise < 0 ? "bg-negative/70" : "bg-positive/75")} style={{ width: `${Math.abs(netPaise) * 100 / max}%` }} />
        </div>
      </li>)}
    </ul>}
  </Card>;
}
