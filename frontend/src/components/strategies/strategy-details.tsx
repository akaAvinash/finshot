import { History, Pause, Play, ShieldCheck, SquarePen } from "lucide-react";
import { useEffect, useRef } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Status } from "@/components/ui/status";
import type { Strategy, StrategyParameters } from "@/lib/api/strategy-types";
import { formatSnapshotDate } from "@/lib/format";
import { activationBlocker, latestStrategyVersion, listedStrategyRevision, riskLabels, strategyCandidate } from "@/lib/strategies";
import { formatBps, StrategyRiskBadge, StrategyStatusBadge } from "./strategy-list";

const backtestLabels = { passed: "Passed", failed: "Failed", unavailable: "Unavailable" } as const;
const reviewLabels = { approved: "Approved", rejected: "Rejected", pending: "Pending" } as const;

function Parameters({ values }: { values: StrategyParameters }) {
  const properties = [
    ["Instrument", values.instrument], ["Timeframe", values.timeframe], ["Risk tier", riskLabels[values.riskTier]],
    ["Position size", formatBps(values.positionSizeBps)], ["Stop loss", formatBps(values.stopLossBps)],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {properties.map(([label, value]) => (
        <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-0.5 text-sm font-medium tabular-nums">{value}</dd></div>
      ))}
    </dl>
  );
}

export function StrategyDetails({ strategy, canWrite, busy, onEdit, onAction, staging }: {
  strategy: Strategy;
  canWrite: boolean;
  busy: boolean;
  onEdit: () => void;
  onAction: (action: "activate" | "pause") => void;
  staging?: boolean;
}) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus(); }, []);

  const shown = listedStrategyRevision(strategy);
  const candidate = strategyCandidate(strategy);
  const version = latestStrategyVersion(strategy);
  if (!shown || !candidate) return null;

  const active = strategy.status === "active";
  const blocker = activationBlocker(candidate);
  return (
    <>
      <DialogTitle ref={title} tabIndex={-1} className="wrap-anywhere">{shown.parameters.name}</DialogTitle>
      <DialogDescription>{shown.parameters.description || "Sample strategy parameters and version history."}</DialogDescription>
      <div className="mt-3 flex flex-wrap gap-2">
        <StrategyStatusBadge status={strategy.status} /><StrategyRiskBadge risk={shown.parameters.riskTier} />
        <Status tone="accent">Demo strategy</Status>
      </div>

      <section aria-label="Strategy parameters" className="mt-5 space-y-3 rounded-xl border border-border bg-background/50 p-4">
        <h3 className="text-sm font-semibold">{strategy.draft ? "Draft parameters" : "Deployed parameters"}</h3>
        {strategy.draft && version && <p className="text-xs wrap-anywhere text-muted-foreground">{candidate.parameters.name} · Version {version.number} remains unchanged.</p>}
        <Parameters values={candidate.parameters} />
      </section>

      <section aria-label="Deployment eligibility" className="mt-4 space-y-2 rounded-xl border border-border p-4">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck aria-hidden className="size-4 text-accent-foreground" /> Deployment eligibility</h3>
        <div className="flex flex-wrap gap-2">
          <Status tone={candidate.backtest === "passed" ? "positive" : "neutral"}>Backtest · {backtestLabels[candidate.backtest]}</Status>
          <Status tone={candidate.riskReview === "approved" ? "positive" : "neutral"}>Risk review · {reviewLabels[candidate.riskReview]}</Status>
        </div>
        <p id="strategy-eligibility" className="text-sm text-muted-foreground">{blocker ?? "Eligible for demo activation. No orders will be placed."}</p>
        {staging && strategy.draft && <Link href="/backtesting" className="inline-block text-sm font-medium text-accent-foreground underline underline-offset-4">Open Backtesting</Link>}
      </section>

      <section aria-label="Version history" className="mt-4 space-y-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><History aria-hidden className="size-4 text-accent-foreground" /> Version history</h3>
        {strategy.versions.length === 0 && <p className="text-sm text-muted-foreground">No deployed versions yet.</p>}
        {[...strategy.versions].reverse().map((entry) => (
          <details key={entry.number} className="rounded-lg border border-border bg-background/50 px-3">
            <summary className="cursor-pointer py-2.5 text-sm font-medium">
              Version {entry.number} <span className="ml-1 text-xs font-normal text-muted-foreground">· <time dateTime={entry.activatedAt}>{formatSnapshotDate(entry.activatedAt)}</time></span>
            </summary>
            <div className="space-y-2 pb-3"><p className="text-sm wrap-anywhere">{entry.parameters.name}</p><Parameters values={entry.parameters} /></div>
          </details>
        ))}
      </section>

      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button variant="outline" className="h-11" disabled={!canWrite || busy} onClick={onEdit}><SquarePen aria-hidden /> Edit draft</Button>
        <Button className="h-11" disabled={!canWrite || busy || (!active && blocker !== null)} aria-describedby={active ? undefined : "strategy-eligibility"}
          onClick={() => onAction(active ? "pause" : "activate")}>
          {active ? <><Pause aria-hidden /> Pause demo</> : <><Play aria-hidden /> Activate demo</>}
        </Button>
      </div>
    </>
  );
}
