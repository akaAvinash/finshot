import { ArrowUpRight, ChartNoAxesCombined, Layers, Pause, Play, SquarePen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { Strategy, StrategyRiskTier, StrategyStatus } from "@/lib/api/strategy-types";
import { formatInr } from "@/lib/format";
import { listedStrategyRevision, riskLabels, strategyStatusLabels } from "@/lib/strategies";
import { cn } from "@/lib/utils";

const statusTones = { active: "positive", paused: "neutral", draft: "accent" } as const;
const riskTones = { low: "positive", medium: "accent", high: "negative" } as const;
const statusIcons = { active: Play, paused: Pause, draft: SquarePen } as const;
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 2 });

export function formatBps(value: number) {
  return percent.format(value / 10_000);
}

export function StrategyStatusBadge({ status }: { status: StrategyStatus }) {
  return <Status tone={statusTones[status]} dot>{strategyStatusLabels[status]}</Status>;
}

export function StrategyRiskBadge({ risk }: { risk: StrategyRiskTier }) {
  return <Status tone={riskTones[risk]}>{riskLabels[risk]} risk</Status>;
}

function StrategyPnl({ metrics }: { metrics: Strategy["metrics"] }) {
  if (!metrics) return <span className="text-muted-foreground">Unavailable</span>;
  const value = metrics.pnlPaise;
  return <span className={cn(value > 0 && "text-positive", value < 0 && "text-negative")}>{formatInr(value / 100, true)}</span>;
}

export function StrategySummary({ strategies }: { strategies: readonly Strategy[] }) {
  const counts = [
    { label: "Total strategies", value: strategies.length, icon: Layers, tone: "text-accent-foreground" },
    { label: "Active demos", value: strategies.filter(({ status }) => status === "active").length, icon: Play, tone: "text-positive" },
    { label: "Paused", value: strategies.filter(({ status }) => status === "paused").length, icon: Pause, tone: "text-muted-foreground" },
    { label: "Drafts", value: strategies.filter(({ draft }) => draft !== null).length, icon: SquarePen, tone: "text-accent-foreground" },
  ];
  return (
    <dl aria-label="Demo strategy summary" className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
      {counts.map(({ label, value, icon: Icon, tone }) => (
        <div key={label} className="flex min-w-0 items-center gap-2.5 rounded-xl border border-border bg-card p-3 sm:p-4">
          <span aria-hidden className={cn("grid size-9 shrink-0 place-items-center rounded-lg bg-surface-raised", tone)}><Icon className="size-4" /></span>
          <div><dt className="text-xs font-medium text-muted-foreground">{label}</dt><dd className="mt-0.5 text-2xl leading-tight font-semibold tabular-nums">{value}</dd></div>
        </div>
      ))}
    </dl>
  );
}

type OpenStrategy = (strategy: Strategy, opener: HTMLButtonElement) => void;

export function StrategyCard({ strategy, onOpen }: { strategy: Strategy; onOpen: OpenStrategy }) {
  const revision = listedStrategyRevision(strategy);
  if (!revision) return null;
  const { name, description, instrument, timeframe, riskTier } = revision.parameters;
  const Icon = statusIcons[strategy.status];
  const headingId = `strategy-${strategy.id}`;
  return (
    <Card aria-labelledby={headingId} className="flex flex-col p-4 transition-colors hover:border-primary/45 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <span aria-hidden className="grid size-10 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-accent-foreground"><Icon className="size-5" /></span>
        <StrategyStatusBadge status={strategy.status} />
      </div>
      <h3 id={headingId} className="mt-3 text-lg font-semibold tracking-tight wrap-anywhere">{name}</h3>
      <p className="mt-1 text-xs font-medium text-muted-foreground">{instrument} <span aria-hidden>·</span> {timeframe}</p>
      <p className="mt-2 flex-1 text-sm leading-relaxed wrap-anywhere text-muted-foreground">{description || "No description added."}</p>
      <dl className="mt-4 grid grid-cols-2 gap-2 rounded-lg border border-border bg-background/50 px-3 py-2.5">
        <div><dt className="text-xs text-muted-foreground">Sample P&L</dt><dd className="mt-1 text-sm font-semibold tabular-nums"><StrategyPnl metrics={strategy.metrics} /></dd></div>
        <div><dt className="text-xs text-muted-foreground">Sample win rate</dt><dd className="mt-1 text-sm font-semibold tabular-nums">{strategy.metrics ? formatBps(strategy.metrics.winRateBps) : <span className="text-muted-foreground">Unavailable</span>}</dd></div>
      </dl>
      <div className="mt-4 flex items-center justify-between gap-2">
        <StrategyRiskBadge risk={riskTier} />
        <Button variant="outline" className="h-11 px-3" aria-label={`View ${name}`} onClick={(event) => onOpen(strategy, event.currentTarget)}>Details <ArrowUpRight aria-hidden /></Button>
      </div>
    </Card>
  );
}

export function StrategyTable({ strategies, onOpen }: { strategies: readonly Strategy[]; onOpen: OpenStrategy }) {
  return (
    <Card className="overflow-hidden">
      <div className="relative overflow-x-auto" role="region" aria-label="Demo strategies table" tabIndex={0}>
        <Table>
          <caption className="sr-only">Demo strategies</caption>
          <thead className="border-b border-border bg-surface-raised/60"><tr>
            <TableHead>Strategy</TableHead><TableHead>Instrument</TableHead><TableHead>Status</TableHead>
            <TableHead>Risk tier</TableHead><TableHead>Sample P&L</TableHead><TableHead>Win rate</TableHead><TableHead><span className="sr-only">Actions</span></TableHead>
          </tr></thead>
          <tbody>
            {strategies.map((strategy) => {
              const revision = listedStrategyRevision(strategy);
              if (!revision) return null;
              const { name, instrument, timeframe, riskTier } = revision.parameters;
              return (
                <tr key={strategy.id} className="border-b border-border last:border-b-0">
                  <th scope="row" className="px-4 py-3 text-left font-medium">{name}</th>
                  <TableCell>{instrument} <span className="text-muted-foreground">· {timeframe}</span></TableCell>
                  <TableCell><StrategyStatusBadge status={strategy.status} /></TableCell>
                  <TableCell><StrategyRiskBadge risk={riskTier} /></TableCell>
                  <TableCell className="tabular-nums"><StrategyPnl metrics={strategy.metrics} /></TableCell>
                  <TableCell className="tabular-nums">{strategy.metrics ? formatBps(strategy.metrics.winRateBps) : "Unavailable"}</TableCell>
                  <TableCell className="text-right"><Button variant="ghost" size="icon" aria-label={`View ${name}`} onClick={(event) => onOpen(strategy, event.currentTarget)}><ChartNoAxesCombined aria-hidden /></Button></TableCell>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </div>
    </Card>
  );
}
