import { Activity, ChartNoAxesCombined, Layers, Receipt, ShieldCheck, Wallet } from "lucide-react";
import type { PaperReport } from "@/lib/api/paper-report-types";
import { formatInr, formatSnapshotDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";

function Money({ paise, signed = true }: { paise: number; signed?: boolean }) {
  return <span className={cn("tabular-nums", signed && paise > 0 && "text-positive", signed && paise < 0 && "text-negative")}>
    {formatInr(paise / 100, signed)}
  </span>;
}

export function ReportMetrics({ summary }: { summary: PaperReport["summary"] }) {
  const wins = `${summary.winningTrades} ${summary.winningTrades === 1 ? "win" : "wins"}`;
  const losses = `${summary.losingTrades} ${summary.losingTrades === 1 ? "loss" : "losses"}`;
  const metrics = [
    { label: "Net P&L", paise: summary.netPaise, note: "Period realised + current unrealised", icon: Wallet },
    { label: "Realised P&L", paise: summary.realisedPaise, note: `${summary.closedTrades} closed · ${wins} · ${losses}`, icon: ChartNoAxesCombined },
    { label: "Unrealised P&L", paise: summary.unrealisedPaise, note: "Current replay at latest mark", icon: Activity },
    { label: "Period fees", paise: summary.feesPaise, note: `${summary.fills} fills across all replays`, icon: Receipt, unsigned: true },
  ];

  return <dl className="grid grid-cols-2 gap-2.5 xl:grid-cols-4" aria-label="Paper report totals">
    {metrics.map(({ label, paise, note, icon: Icon, unsigned }) => <div key={label} className="min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4">
      <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Icon aria-hidden className="size-4 shrink-0 text-accent-foreground" />{label}</dt>
      <dd className="mt-2 text-xl font-semibold tracking-tight wrap-anywhere sm:text-2xl"><Money paise={paise} signed={!unsigned} /></dd>
      <dd className="mt-1 text-xs leading-relaxed text-muted-foreground">{note}</dd>
    </div>)}
  </dl>;
}

export function StrategyBreakdown({ rows }: { rows: PaperReport["strategies"] }) {
  return <Card aria-labelledby="report-strategies" className="min-w-0 p-4 sm:p-5">
    <h2 id="report-strategies" className="flex items-center gap-2 font-semibold"><Layers aria-hidden className="size-4 text-accent-foreground" /> By strategy version</h2>
    {rows.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">No fills in this period.</p> : <ul className="mt-2 divide-y divide-border">
      {rows.map(({ strategy, realisedPaise, closedTrades, fills }) => <li key={strategy ? `${strategy.id}:${strategy.version}` : "unattributed"} className="flex flex-wrap items-start justify-between gap-2 py-2.5 last:pb-0">
        <div className="min-w-0">
          <p className="font-medium wrap-anywhere">{strategy ? `${strategy.name} · v${strategy.version}` : "Unattributed fills"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{fills} {fills === 1 ? "fill" : "fills"} · {closedTrades} closed</p>
        </div>
        <p className="text-sm font-semibold"><Money paise={realisedPaise} /></p>
      </li>)}
    </ul>}
  </Card>;
}

export function CurrentReplay({ position, reconciliation }: {
  position: PaperReport["openPosition"];
  reconciliation: PaperReport["reconciliation"];
}) {
  return <Card aria-labelledby="report-replay" className="min-w-0 p-4 sm:p-5">
    <h2 id="report-replay" className="flex items-center gap-2 font-semibold"><ShieldCheck aria-hidden className="size-4 text-accent-foreground" /> Current replay</h2>
    {position ? <div className="mt-3 space-y-1 text-sm">
      <p className="font-medium">{position.instrument} <span className="font-normal text-muted-foreground">· {position.quantity} open</span></p>
      <p className="text-muted-foreground">{formatInr(position.entryPaise / 100)} entry · {formatInr(position.markPaise / 100)} mark</p>
      <p><Money paise={position.unrealisedPaise} /> <span className="text-xs text-muted-foreground">unrealised · marked {formatSnapshotDate(position.markedAt)}</span></p>
    </div> : <p className="mt-3 text-sm text-muted-foreground">No open position.</p>}

    {reconciliation && <div className="mt-3 border-t border-border pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p>Ledger check · replay {reconciliation.replay}</p>
        <Status tone={reconciliation.status === "matched" ? "positive" : "negative"}>
          {reconciliation.status === "matched" ? "Matched" : "Mismatch"}
        </Status>
      </div>
      {reconciliation.status === "mismatch" && <p role="alert" className="mt-2 text-sm text-negative">
        Ledger cash {formatInr(reconciliation.ledgerCashPaise / 100)} · account cash {formatInr(reconciliation.accountCashPaise / 100)}.
        {` Ledger quantity ${reconciliation.ledgerQuantity} · account quantity ${reconciliation.accountQuantity}.`}
      </p>}
    </div>}
  </Card>;
}
