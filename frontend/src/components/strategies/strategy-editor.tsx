import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { strategyInstruments, strategyRiskTiers, strategyTimeframes, type StrategyParameters } from "@/lib/api/strategy-types";
import { riskLabels, validateStrategyParameters } from "@/lib/strategies";

const defaults: StrategyParameters = {
  name: "", description: "", instrument: "NIFTY 50", timeframe: "15m", riskTier: "medium", positionSizeBps: 500, stopLossBps: 100,
};

export const strategySelectClass = "h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-base text-foreground sm:text-sm";

function asBasisPoints(value: FormDataEntryValue | null) {
  const text = String(value ?? "");
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return Number.NaN;
  return Math.round(Number(text) * 100);
}

export function StrategyEditor({ initial, busy, onCancel, onSave }: {
  initial?: StrategyParameters;
  busy: boolean;
  onCancel: () => void;
  onSave: (parameters: StrategyParameters) => Promise<void>;
}) {
  const parameters = initial ?? defaults;
  const [validationError, setValidationError] = useState<string | null>(null);
  const nameField = useRef<HTMLInputElement>(null);

  useEffect(() => { nameField.current?.focus(); }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const draft: StrategyParameters = {
      name: String(fields.get("name") ?? ""),
      description: String(fields.get("description") ?? ""),
      instrument: strategyInstruments.find((value) => value === fields.get("instrument")) ?? parameters.instrument,
      timeframe: strategyTimeframes.find((value) => value === fields.get("timeframe")) ?? parameters.timeframe,
      riskTier: strategyRiskTiers.find((value) => value === fields.get("riskTier")) ?? parameters.riskTier,
      positionSizeBps: asBasisPoints(fields.get("positionSize")),
      stopLossBps: asBasisPoints(fields.get("stopLoss")),
    };

    const error = validateStrategyParameters(draft);
    setValidationError(error);
    if (!error) void onSave(draft);
  }

  return (
    <>
      <DialogTitle>{initial ? "Edit strategy draft" : "Create strategy draft"}</DialogTitle>
      <DialogDescription>Save sample parameters for review. Edited drafts require a fresh backtest and risk review.</DialogDescription>
      <form className="mt-5" onSubmit={submit}>
        <fieldset disabled={busy} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="strategy-name">Strategy name</Label>
            <Input ref={nameField} id="strategy-name" name="name" defaultValue={parameters.name} placeholder="NIFTY range practice" required minLength={3} maxLength={64} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="strategy-description">Description <span className="text-muted-foreground">(optional)</span></Label>
            <textarea id="strategy-description" name="description" defaultValue={parameters.description} maxLength={240} rows={2} className="w-full rounded-lg border border-input bg-background px-3 py-2 text-base sm:text-sm" />
          </div>
          <div className="space-y-1.5"><Label htmlFor="strategy-instrument">Instrument</Label>
            <select id="strategy-instrument" name="instrument" defaultValue={parameters.instrument} className={strategySelectClass}>
              {strategyInstruments.map((instrument) => <option key={instrument}>{instrument}</option>)}
            </select>
          </div>
          <div className="space-y-1.5"><Label htmlFor="strategy-timeframe">Timeframe</Label>
            <select id="strategy-timeframe" name="timeframe" defaultValue={parameters.timeframe} className={strategySelectClass}>
              {strategyTimeframes.map((timeframe) => <option key={timeframe}>{timeframe}</option>)}
            </select>
          </div>
          <div className="space-y-1.5"><Label htmlFor="strategy-size">Position size (%)</Label>
            <Input id="strategy-size" name="positionSize" type="number" min="0.01" max="100" step="0.01" defaultValue={parameters.positionSizeBps / 100} required />
          </div>
          <div className="space-y-1.5"><Label htmlFor="strategy-stop">Stop loss (%)</Label>
            <Input id="strategy-stop" name="stopLoss" type="number" min="0.01" max="100" step="0.01" defaultValue={parameters.stopLossBps / 100} required />
          </div>
          <div className="space-y-1.5"><Label htmlFor="strategy-risk">Risk tier</Label>
            <select id="strategy-risk" name="riskTier" defaultValue={parameters.riskTier} className={strategySelectClass}>
              {strategyRiskTiers.map((risk) => <option key={risk} value={risk}>{riskLabels[risk]}</option>)}
            </select>
          </div>
        </fieldset>
        {validationError && <p role="alert" className="mt-3 text-sm text-negative">{validationError}</p>}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button variant="outline" className="h-11" disabled={busy} onClick={onCancel}>Cancel</Button>
          <Button type="submit" className="h-11" disabled={busy}>{busy ? "Saving draft…" : "Save draft"}</Button>
        </div>
      </form>
    </>
  );
}
