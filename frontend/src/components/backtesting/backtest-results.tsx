import { useMemo, useState } from "react";
import { Activity, ChartNoAxesCombined, Download, List, ShieldAlert, Wallet } from "lucide-react";
import { DataState } from "@/components/data-state";
import { PortfolioChart } from "@/components/dashboard/portfolio-chart";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { BacktestRun, BacktestWorkspace } from "@/lib/api/backtest-types";
import { backtestTradesCsv, formatBacktestTime } from "@/lib/backtesting";
import { formatInr, formatPercent, formatSnapshotDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type Completed = Extract<BacktestRun, { status: "completed" }>;
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 2 });
const drawdownLabel = (value: number) => percent.format(value / 100);

function writeCsv(run: Completed) {
  const file = new Blob([backtestTradesCsv(run)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = `tradeo-demo-${run.id}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function BacktestPerformance({ run }: { run: Completed }) {
  const [view, setView] = useState<"equity" | "drawdown">("equity");
  const points = useMemo(() => run.result.points.map((point) => ({
    date: point.date, value: view === "equity" ? point.equityPaise / 100 : point.drawdownBps / 100,
  })), [run.result.points, view]);

  return (
    <Card aria-labelledby="backtest-performance" className="min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 sm:px-5">
        <h3 id="backtest-performance" className="flex items-center gap-2 font-semibold"><Activity aria-hidden className="size-4 text-accent-foreground" /> Holdout performance</h3>
        <div className="flex gap-1 rounded-lg border border-border bg-background/50 p-0.5" role="group" aria-label="Performance chart view">
          <Button size="sm" className="h-10" variant={view === "equity" ? "default" : "ghost"} aria-pressed={view === "equity"} onClick={() => setView("equity")}>Equity</Button>
          <Button size="sm" className="h-10" variant={view === "drawdown" ? "default" : "ghost"} aria-pressed={view === "drawdown"} onClick={() => setView("drawdown")}>Drawdown</Button>
        </div>
      </div>
      <p className="px-4 pt-3 text-xs text-muted-foreground sm:px-5">{view === "equity" ? "Daily closing mark in INR, after applied fills and fees." : "Daily percentage below the running equity peak."}</p>
      <div className="relative mx-3 my-3 h-58 sm:mx-4 sm:h-72">
        <PortfolioChart points={points} label={view === "equity" ? "Demo equity curve" : "Demo drawdown chart"}
          tone={view === "drawdown" ? "negative" : "gold"} formatValue={view === "drawdown" ? drawdownLabel : undefined} />
      </div>
    </Card>
  );
}

function BacktestTrades({ run }: { run: Completed }) {
  const { trades, totalFeesPaise } = run.result;
  return (
    <Card aria-labelledby="backtest-trades" className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 sm:px-5">
        <div>
          <h3 id="backtest-trades" className="flex items-center gap-2 font-semibold"><List aria-hidden className="size-4 text-accent-foreground" /> Simulated trades</h3>
          <p className="mt-1 text-xs text-muted-foreground">{trades.length} closed · {formatInr(totalFeesPaise / 100)} fees · All times IST</p>
        </div>
        <Button variant="outline" className="h-11" disabled={trades.length === 0} onClick={() => writeCsv(run)}><Download aria-hidden /> Export CSV</Button>
      </div>
      {trades.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No fills occurred in this holdout window.</p> : (
        <div className="relative overflow-x-auto" role="region" tabIndex={0} aria-label="Simulated trades table">
          <Table>
            <caption className="sr-only">Closed trades for this demo run</caption>
            <thead className="border-b border-border bg-surface-raised/55"><tr>
              <TableHead>Entry</TableHead><TableHead>Exit</TableHead><TableHead>Units</TableHead><TableHead>Entry price</TableHead>
              <TableHead>Exit price</TableHead><TableHead>Net P&L</TableHead>
            </tr></thead>
            <tbody>
              {trades.map((trade) => <tr key={trade.id} className="border-b border-border tabular-nums last:border-b-0">
                <TableCell><time dateTime={trade.entryAt}>{formatBacktestTime(trade.entryAt)}</time></TableCell>
                <TableCell><time dateTime={trade.exitAt}>{formatBacktestTime(trade.exitAt)}</time></TableCell>
                <TableCell>{trade.quantity}</TableCell><TableCell>{formatInr(trade.entryPaise / 100)}</TableCell><TableCell>{formatInr(trade.exitPaise / 100)}</TableCell>
                <TableCell className={cn("font-medium", trade.pnlPaise > 0 && "text-positive", trade.pnlPaise < 0 && "text-negative")}>{formatInr(trade.pnlPaise / 100, true)}</TableCell>
              </tr>)}
            </tbody>
          </Table>
        </div>
      )}
    </Card>
  );
}

export function BacktestResults({ run, workspace }: { run: BacktestRun | undefined; workspace: BacktestWorkspace }) {
  if (!run) return <DataState title="No backtest results yet" description="Choose a strategy revision and run a simulation to populate this workspace." icon={ChartNoAxesCombined} />;
  if (run.status === "failed") return <DataState error title="Demo backtest failed" description={run.message} />;
  if (run.status !== "completed") {
    return <Card className="grid min-h-56 place-content-center p-6 text-center" role="status">
      <p className="font-semibold">{run.status === "queued" ? "Demo run queued" : "Demo run in progress"}</p>
      <p className="mt-2 text-sm text-muted-foreground">Performance and trades appear once the run finishes.</p>
    </Card>;
  }

  const { result, config } = run;
  const strategy = workspace.strategies.find(({ id }) => id === config.strategyId);
  const instrument = workspace.instruments.find(({ id }) => id === config.instrumentId);
  const pnlTone = result.netPnlPaise < 0 ? "text-negative" : result.netPnlPaise > 0 ? "text-positive" : "text-foreground";
  const metrics = [
    { label: "Ending equity", value: formatInr(result.endingEquityPaise / 100), note: `Start ${formatInr(config.capitalPaise / 100)}`, icon: Wallet, tone: "text-foreground" },
    { label: "Net P&L", value: formatInr(result.netPnlPaise / 100, true), note: formatPercent(result.returnBps / 100), icon: ChartNoAxesCombined, tone: pnlTone },
    { label: "Max drawdown", value: percent.format(result.maxDrawdownBps / 10_000), note: "Peak to trough", icon: ShieldAlert, tone: result.maxDrawdownBps < 0 ? "text-negative" : "text-foreground" },
    { label: "Win rate", value: result.winRateBps === null ? "Unavailable" : percent.format(result.winRateBps / 10_000), note: `${result.trades.length} closed trades`, icon: Activity, tone: "text-foreground" },
  ];
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Demo backtest results</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{strategy?.name} · {strategy?.revision === "draft" ? "Draft" : `v${strategy?.revision}`} · {instrument?.symbol}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Holdout · {formatSnapshotDate(config.outOfSampleFrom)} to {formatSnapshotDate(config.to)} IST</p>
        </div>
        <Status tone="positive" dot>Completed</Status>
      </div>
      <dl className="grid grid-cols-2 gap-2.5 md:grid-cols-4" aria-label="Demo backtest metrics">
        {metrics.map(({ label, value, note, icon: Icon, tone }) => (
          <div className="min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4" key={label}>
            <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Icon aria-hidden className="size-4 shrink-0 text-accent-foreground" />{label}</dt>
            <dd className={cn("mt-2 text-lg font-semibold tracking-tight tabular-nums wrap-anywhere", tone)}>{value}</dd>
            <dd className="mt-1 text-xs text-muted-foreground">{note}</dd>
          </div>
        ))}
      </dl>
      <BacktestPerformance key={run.id} run={run} />
      <BacktestTrades run={run} />
    </>
  );
}
