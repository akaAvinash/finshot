import { Play, Settings2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { exampleBacktestConfig } from "@/lib/api/backtest-mock";
import type { BacktestConfig, BacktestWorkspace } from "@/lib/api/backtest-types";
import { maxCapitalPaise, maxCostBps, minCapitalPaise, validateBacktestConfig } from "@/lib/backtesting";
import { formatSnapshotDate } from "@/lib/format";

const selectClass = "h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-base text-foreground sm:text-sm";

export function BacktestForm({ workspace, canRun, busy, onRun }: {
  workspace: BacktestWorkspace;
  canRun: boolean;
  busy: boolean;
  onRun: (config: BacktestConfig) => Promise<void>;
}) {
  const defaults = exampleBacktestConfig;
  const [strategyId, setStrategyId] = useState(defaults.strategyId);
  const [instrumentId, setInstrumentId] = useState(defaults.instrumentId);
  const [validation, setValidation] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const config: BacktestConfig = {
      strategyId,
      instrumentId,
      from: String(values.get("from") ?? ""),
      to: String(values.get("to") ?? ""),
      outOfSampleFrom: String(values.get("holdout") ?? ""),
      capitalPaise: Math.round(Number(values.get("capital")) * 100),
      feeBps: Number(values.get("fee")),
      slippageBps: Number(values.get("slippage")),
    };
    const error = validateBacktestConfig(config, workspace);
    setValidation(error);
    if (!error) void onRun(config);
  }

  return (
    <Card aria-labelledby="backtest-setup" className="p-4 sm:p-5">
      <h2 id="backtest-setup" className="flex items-center gap-2 font-semibold tracking-tight"><Settings2 aria-hidden className="size-4 text-accent-foreground" /> Backtest setup</h2>
      <p id="backtest-range" className="mt-1 text-xs leading-relaxed text-muted-foreground">Demo sessions from {formatSnapshotDate(workspace.from)} to {formatSnapshotDate(workspace.to)} IST.</p>
      <form className="mt-4" onSubmit={submit}>
        <fieldset disabled={!canRun || busy} className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-1">
          <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-strategy">Strategy revision</Label>
            <select id="backtest-strategy" className={selectClass} value={strategyId} onChange={({ target }) => {
              const strategy = workspace.strategies.find(({ id }) => id === target.value);
              if (strategy) {
                setStrategyId(strategy.id);
                setInstrumentId(strategy.instrumentId);
              }
            }}>
              {workspace.strategies.map((strategy) => <option key={strategy.id} value={strategy.id}>{strategy.name} · {strategy.revision === "draft" ? "Draft" : `v${strategy.revision}`}</option>)}
            </select>
          </div>
          <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-instrument">Instrument</Label>
            <select id="backtest-instrument" className={selectClass} value={instrumentId} onChange={({ target }) => setInstrumentId(target.value)}>
              {workspace.instruments.map(({ id, symbol }) => <option key={id} value={id}>{symbol}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-1 gap-3 min-[365px]:grid-cols-2 sm:col-span-2 xl:col-span-1">
            <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-from">Start date</Label>
              <Input id="backtest-from" name="from" type="date" className="px-2" min={workspace.from} max={workspace.to} defaultValue={defaults.from} aria-describedby="backtest-range" required />
            </div>
            <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-to">End date</Label>
              <Input id="backtest-to" name="to" type="date" className="px-2" min={workspace.from} max={workspace.to} defaultValue={defaults.to} aria-describedby="backtest-range" required />
            </div>
          </div>
          <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-holdout">Out-of-sample start</Label>
            <Input id="backtest-holdout" name="holdout" type="date" min={workspace.from} max={workspace.to} defaultValue={defaults.outOfSampleFrom} aria-describedby="backtest-holdout-help" required />
            <p id="backtest-holdout-help" className="text-xs leading-relaxed text-muted-foreground">Earlier sessions warm up the signal. Results use only this holdout period.</p>
          </div>
          <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-capital">Starting capital (INR)</Label>
            <Input id="backtest-capital" name="capital" type="number" min={minCapitalPaise / 100} max={maxCapitalPaise / 100} step="0.01" defaultValue={defaults.capitalPaise / 100} required />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:col-span-2 xl:col-span-1">
            <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-fee">Fees (bps)</Label>
              <Input id="backtest-fee" name="fee" type="number" min="0" max={maxCostBps} step="1" defaultValue={defaults.feeBps} required />
            </div>
            <div className="min-w-0 space-y-1.5"><Label htmlFor="backtest-slippage">Slippage (bps)</Label>
              <Input id="backtest-slippage" name="slippage" type="number" min="0" max={maxCostBps} step="1" defaultValue={defaults.slippageBps} required />
            </div>
          </div>
        </fieldset>
        <p className="mt-2 text-xs text-muted-foreground">Applied per fill. 1 bps equals 0.01%.</p>
        {validation && <p role="alert" className="mt-3 text-sm text-negative">{validation}</p>}
        <Button type="submit" className="mt-4 h-11 w-full" disabled={!canRun || busy}><Play aria-hidden /> {busy ? "Demo run in progress" : "Run demo backtest"}</Button>
      </form>
      <details className="mt-4 border-t border-border pt-3">
        <summary className="cursor-pointer text-sm font-medium">Simulation assumptions</summary>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">The preview uses a shared three-session moving-average rule and the selected revision&apos;s position size. Signals use completed daily demo candles. Orders fill at the next session open, with costs and whole demo units. Positions close by the last holdout session. Results cannot approve a strategy for deployment.</p>
      </details>
    </Card>
  );
}
