"use client";

import { useState, type FormEvent } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import type { PaperCommand, PaperLimits, PaperSnapshot } from "@/lib/api/auto-trading-types";
import { formatInr } from "@/lib/format";
import { getPaperTradeControls, validatePaperLimits } from "@/lib/paper-trade-controls";

function LimitField({ name, label, value, min = 0.01, max, whole, optional, suffix, help }: {
  name: keyof PaperLimits;
  label: string;
  value: number | "";
  min?: number;
  max?: number;
  whole?: boolean;
  optional?: boolean;
  suffix?: string;
  help?: string;
}) {
  const id = `trade-limit-${name}`;
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={id} className="block">{label}</Label>
      <div className="relative">
        <Input id={id} name={name} type="number" inputMode={whole ? "numeric" : "decimal"} min={min} max={max}
          step={whole ? 1 : 0.01} defaultValue={value} required={!optional} placeholder={optional ? "Off" : undefined}
          aria-describedby={help ? `${id}-help` : undefined} className={suffix ? "pr-10" : undefined} />
        {suffix && <span aria-hidden className="pointer-events-none absolute inset-y-0 right-3 grid place-items-center text-sm text-muted-foreground">{suffix}</span>}
      </div>
      {help && <p id={`${id}-help`} className="text-xs leading-relaxed text-muted-foreground">{help}</p>}
    </div>
  );
}

export function TradeControls({ snapshot, stale, pending, onRun }: {
  snapshot: PaperSnapshot;
  stale: boolean;
  pending: boolean;
  onRun: (command: PaperCommand) => Promise<boolean>;
}) {
  const [validation, setValidation] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const { risk, engine, sampleEntry } = snapshot;
  const controls = getPaperTradeControls(snapshot);
  const disabled = stale || pending || engine !== "idle";
  const rupees = (paise: number) => formatInr(paise / 100);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled) return;
    const values = new FormData(event.currentTarget);
    const number = (name: keyof PaperLimits) => Number(values.get(name));
    const hundredths = (name: keyof PaperLimits) => Math.round(number(name) * 100);
    const limits: PaperLimits = {
      profitLimitPaise: values.get("profitLimitPaise") === "" ? null : hundredths("profitLimitPaise"),
      lossLimitPaise: hundredths("lossLimitPaise"),
      tradeLimit: number("tradeLimit"),
      postCapConfidencePercent: number("postCapConfidencePercent"),
      maxConsecutiveLosses: number("maxConsecutiveLosses"),
      stopLossBps: hundredths("stopLossBps"),
      takeProfitBps: hundredths("takeProfitBps"),
      maxRiskPerTradePaise: hundredths("maxRiskPerTradePaise"),
      maxPositionSizeBps: hundredths("maxPositionSizeBps"),
    };
    const error = validatePaperLimits(limits);
    setValidation(error);
    setSaved(!error && await onRun({ action: "set-limits", limits }));
  }

  return (
    <Card aria-labelledby="trade-controls-heading" className="p-4 sm:p-5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 id="trade-controls-heading" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <SlidersHorizontal aria-hidden className="size-5 text-accent-foreground" /> Trade controls
        </h2>
        <Status>Paper preview</Status>
      </header>
      <dl className="my-4 grid grid-cols-2 gap-x-4 gap-y-4 text-sm lg:grid-cols-4 lg:gap-x-0 lg:[&>div+div]:border-l lg:[&>div+div]:border-border lg:[&>div+div]:pl-5 lg:[&>div]:pr-5">
        <div>
          <dt className="text-muted-foreground">Realised P&amp;L today</dt>
          <dd className={`mt-1 text-lg font-semibold tabular-nums ${controls.netPaise < 0 ? "text-negative" : controls.netPaise > 0 ? "text-positive" : ""}`}>
            {formatInr(controls.netPaise / 100, true)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Peak profit today</dt>
          <dd className="mt-1 text-lg font-semibold tabular-nums">{rupees(controls.peakPaise)}</dd>
          <dd className="text-xs text-muted-foreground">Highest realised P&amp;L</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Loss used</dt>
          <dd className="mt-1 font-semibold tabular-nums">{rupees(risk.dailyLossPaise)} / {rupees(risk.lossLimitPaise)}
            <progress className="paper-progress mt-1" aria-label="Demo daily loss cap" value={risk.dailyLossPaise} max={risk.lossLimitPaise} />
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Trades used</dt>
          <dd className="mt-1 font-semibold tabular-nums">{risk.tradesToday} / {risk.tradeLimit}
            <progress className="paper-progress mt-1" aria-label="Demo daily trade limit" value={risk.tradesToday} max={risk.tradeLimit} />
          </dd>
        </div>
      </dl>
      {controls.limitReached && <p role="status" className="mb-4 rounded-lg border border-negative/30 px-3 py-2 text-sm text-negative">{controls.limitReached}</p>}
      {controls.profitCapReached && !controls.limitReached && <p role="status" className="mb-4 text-sm text-muted-foreground">
        Profit cap reached. The sample entry meets the {risk.postCapConfidencePercent}% confidence requirement.
      </p>}

      <form onSubmit={save} onChange={() => { setValidation(null); setSaved(false); }}>
        <fieldset disabled={disabled} className="space-y-4 border-t border-border pt-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <LimitField name="profitLimitPaise" label="Daily profit cap (₹)" value={risk.profitLimitPaise === null ? "" : risk.profitLimitPaise / 100} optional />
            <LimitField name="lossLimitPaise" label="Daily loss cap (₹)" value={risk.lossLimitPaise / 100} />
            <LimitField name="tradeLimit" label="Max trades per day" value={risk.tradeLimit} min={1} whole />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <LimitField name="postCapConfidencePercent" label="Confidence needed after the profit cap" value={risk.postCapConfidencePercent}
              min={0} max={100} whole suffix="%" help={`Minimum confidence for a new entry after the cap. Sample entry: ${sampleEntry.confidencePercent ?? "unavailable"}${sampleEntry.confidencePercent === null ? "" : "%"}.`} />
            <LimitField name="maxConsecutiveLosses" label="Stop for the day after this many losses in a row" value={risk.maxConsecutiveLosses}
              min={0} whole help="Blocks new entries for the day. Set to 0 to turn it off." />
          </div>
          <div className="space-y-3 border-t border-border pt-4">
            <h3 className="font-semibold tracking-tight">Per-trade risk controls</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <LimitField name="stopLossBps" label="Stop loss (%)" value={risk.stopLossBps / 100} max={99.99} />
              <LimitField name="takeProfitBps" label="Take profit (%)" value={risk.takeProfitBps / 100} max={100} />
              <LimitField name="maxRiskPerTradePaise" label="Max risk per trade (₹)" value={risk.maxRiskPerTradePaise / 100} />
              <LimitField name="maxPositionSizeBps" label="Max position size (%)" value={risk.maxPositionSizeBps / 100} max={100} />
            </div>
            <p className="text-xs text-muted-foreground">Stop loss and take profit use the entry price. Position size uses paper equity.</p>
            <p className="text-xs text-muted-foreground">
              Sample long entry at {rupees(sampleEntry.pricePaise)} · Stop {rupees(controls.stopPaise)} · Target {rupees(controls.targetPaise)} · Max {controls.maxQuantity} units
            </p>
          </div>
          {validation && <p role="alert" className="text-sm text-negative">{validation}</p>}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-xs text-muted-foreground">Limits apply to this paper preview and reset when you leave the page.
              {engine !== "idle" && " Return the paper engine to idle to edit."}
            </p>
            <Button type="submit" className="h-11">{pending ? "Updating…" : "Save demo limits"}</Button>
          </div>
        </fieldset>
        {saved && <p role="status" className="mt-2 text-sm text-positive">Demo trade limits saved.</p>}
      </form>
    </Card>
  );
}
