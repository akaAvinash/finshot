"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { AuthError, verifyAccountStepUp } from "@/lib/auth/browser-client";
import { isUnconfirmedStagingWrite, stagingError } from "@/lib/api/staging-client";
import {
  getTradeControlHistory, getTradeControlSettings, saveTradeControlSettings, tradeControlFieldErrors, tradeControlFields,
  type TradeControlBound, type TradeControlChange, type TradeControlField, type TradeControlSettings, type TradeControlValues,
} from "@/lib/api/trade-controls-client";
import { formatSnapshotDate } from "@/lib/format";

const fields = {
  lossLimitPaise: { label: "Daily loss limit (₹)", scale: 100, blank: "" },
  tradeLimit: { label: "Maximum trades per session", scale: 1, blank: "" },
  profitLimitPaise: { label: "Daily profit cap (₹)", scale: 100, blank: "Off" },
  maxConsecutiveLosses: { label: "Consecutive losses before stopping", scale: 1, blank: "" },
  stopLossBps: { label: "Stop-loss cap (%)", scale: 100, blank: "Strategy stop" },
  takeProfitBps: { label: "Take-profit target (%)", scale: 100, blank: "Off" },
  maxRiskPerTradePaise: { label: "Maximum risk per trade (₹)", scale: 100, blank: "" },
  maxPositionSizeBps: { label: "Maximum position size (%)", scale: 100, blank: "" },
} as const satisfies Record<TradeControlField, { label: string; scale: number; blank: string }>;

function range(field: TradeControlField, bound: TradeControlBound) {
  const { scale, blank } = fields[field];
  return `${bound.minimum / scale}–${bound.maximum / scale}${bound.nullable ? ` · Blank uses ${blank.toLowerCase()}` : ""}`;
}

function display(field: TradeControlField, value: number | null) {
  if (value === null) return fields[field].blank || "Unset";
  if (field === "maxConsecutiveLosses" && value === 0) return "Off";
  return String(value / fields[field].scale);
}

type Errors = Partial<Record<TradeControlField, string>>;

function readForm(form: HTMLFormElement, bounds: TradeControlSettings["bounds"]) {
  const source = new FormData(form);
  const values: Record<string, number | null> = {};
  const errors: Errors = {};
  for (const field of tradeControlFields) {
    const raw = String(source.get(field) ?? "").trim();
    const { scale } = fields[field];
    const limit = bounds[field];
    if (!raw && limit.nullable) values[field] = null;
    else {
      const valid = scale === 1 ? /^\d+$/.test(raw) : /^\d+(\.\d{1,2})?$/.test(raw);
      const value = Math.round(Number(raw) * scale);
      if (!valid || !Number.isSafeInteger(value) || value < limit.minimum || value > limit.maximum ||
          (value === 0 && field !== "maxConsecutiveLosses")) errors[field] = `Enter a value in ${range(field, limit)}.`;
      else values[field] = value;
    }
  }
  return { values: values as TradeControlValues, errors };
}

export function StagingTradeControls({ readOnly, engineRunning, onSaved }: { readOnly?: boolean; engineRunning: boolean; onSaved: () => void }) {
  const [settings, setSettings] = useState<TradeControlSettings>();
  const [error, setError] = useState("");
  const [history, setHistory] = useState<TradeControlChange[]>();
  const [historyError, setHistoryError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const notify = useNotification();

  useEffect(() => {
    const controller = new AbortController();
    void getTradeControlSettings(controller.signal).then((data) => {
      if (!controller.signal.aborted) { setSettings(data); setError(""); }
    }, (reason: unknown) => {
      if (!controller.signal.aborted) setError(stagingError(reason, "Paper Trade Controls could not load."));
    });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    void getTradeControlHistory(controller.signal).then((data) => {
      if (!controller.signal.aborted) { setHistory(data); setHistoryError(""); }
    }, (reason: unknown) => {
      if (!controller.signal.aborted) setHistoryError(stagingError(reason, "Trade Controls history could not load."));
    });
    return () => controller.abort();
  }, [historyRefresh]);

  function reload() {
    setSettings(undefined);
    setError("");
    setRefresh((value) => value + 1);
    setHistoryRefresh((value) => value + 1);
  }

  return <Card aria-labelledby="paper-trade-controls" className="space-y-4 p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="paper-trade-controls" className="font-semibold">Trade Controls</h2><Status tone="accent">Paper only</Status>
    </div>
    {readOnly && <p className="text-sm text-muted-foreground">Tester accounts have read-only access to paper limits.</p>}
    {!readOnly && engineRunning && <p role="status" className="text-sm text-muted-foreground">Pause the paper engine before editing these limits.</p>}
    {error && <div className="space-y-2"><p role="alert" className="text-sm text-negative">{error}</p>
      <Button variant="outline" onClick={reload}>Retry Trade Controls</Button></div>}
    {!settings && !error && <p role="status" className="text-sm text-muted-foreground">Loading paper limits…</p>}
    {settings && readOnly && <dl className="grid gap-3 sm:grid-cols-2">
      {tradeControlFields.map((field) => <div key={field} className="rounded-lg border border-border p-3">
        <dt className="text-sm text-muted-foreground">{fields[field].label}</dt>
        <dd className="font-medium">{display(field, settings.controls[field])}</dd>
      </div>)}
    </dl>}
    {settings && !readOnly && <TradeControlForm key={`${refresh}:${settings.revision}`} settings={settings} engineRunning={engineRunning}
      onReload={reload} onSave={(next, message = "Paper Trade Controls saved.") => {
        setSettings(next);
        setHistoryRefresh((value) => value + 1);
        onSaved();
        notify(message);
      }} />}
    <details className="rounded-lg border border-border p-3">
      <summary className="cursor-pointer text-sm font-semibold">Trade Controls history</summary>
      {historyError && <div className="mt-2 space-y-2"><p role="alert" className="text-sm text-negative">{historyError}</p>
        <Button variant="outline" size="sm" onClick={() => setHistoryRefresh((value) => value + 1)}>Retry history</Button></div>}
      {!history && !historyError && <p role="status" className="mt-2 text-sm text-muted-foreground">Loading change history…</p>}
      {history?.length === 0 && <p className="mt-2 text-sm text-muted-foreground">No changes saved yet.</p>}
      {!!history?.length && <ol className="mt-3 divide-y divide-border">
        {history.map(({ revision, changedAt, fields: changes }) => <li key={revision} className="space-y-1 py-2 text-sm">
          <p className="font-medium">Revision {revision} · <time dateTime={changedAt}>{formatSnapshotDate(changedAt)} IST</time></p>
          <ul className="text-muted-foreground">{changes.map(({ field, from, to }) => <li key={field}>
            {fields[field].label} · {display(field, from)} → {display(field, to)}
          </li>)}</ul>
        </li>)}
      </ol>}
    </details>
  </Card>;
}

function TradeControlForm({ settings, engineRunning, onReload, onSave }: {
  settings: TradeControlSettings; engineRunning: boolean; onReload: () => void;
  onSave: (settings: TradeControlSettings, message?: string) => void;
}) {
  const [pendingValues, setPendingValues] = useState<TradeControlValues>();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revisionConflict, setRevisionConflict] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const writing = useRef<AbortController | null>(null);
  const codeField = useRef<HTMLInputElement>(null);
  useEffect(() => { if (pendingValues) codeField.current?.focus(); }, [pendingValues]);
  useEffect(() => () => writing.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (writing.current || engineRunning || revisionConflict) return;
    const draft = pendingValues ? { values: pendingValues, errors: {} } : readForm(event.currentTarget, settings.bounds);
    setErrors(draft.errors);
    if (Object.keys(draft.errors).length) { setError("Check the highlighted paper limits."); return; }
    if (pendingValues && !/^\d{6}$/.test(code)) { setError("Enter the six-digit authenticator code."); return; }

    const controller = new AbortController();
    writing.current = controller;
    setBusy(true);
    setError("");
    let saveStarted = false;
    try {
      if (pendingValues) await verifyAccountStepUp(code);
      if (controller.signal.aborted) return;
      saveStarted = true;
      const saved = await saveTradeControlSettings(settings.revision, draft.values, controller.signal);
      if (!controller.signal.aborted) { setPendingValues(undefined); setCode(""); onSave(saved); }
    } catch (reason) {
      if (controller.signal.aborted) return;
      setCode("");
      if (saveStarted && isUnconfirmedStagingWrite(reason)) {
        setPendingValues(undefined);
        try {
          const latest = await getTradeControlSettings(controller.signal);
          if (controller.signal.aborted) return;
          if (latest.revision >= settings.revision && tradeControlFields.every((field) => latest.controls[field] === draft.values[field])) {
            onSave(latest, "Your changes match the current saved limits.");
            return;
          }
          setError(stagingError(reason, "The save could not be confirmed. Load the latest saved limits before trying again."));
        } catch {
          if (controller.signal.aborted) return;
          setError(stagingError(reason, "The save could not be confirmed and the server limits could not be checked. Load the latest saved limits before trying again."));
        }
        setRevisionConflict(true);
        return;
      }
      if (reason instanceof AuthError && reason.code === "STEP_UP_REQUIRED") {
        setPendingValues(draft.values);
        return;
      }
      if (reason instanceof AuthError && (reason.code === "INVALID_TOTP" || (pendingValues && reason.status === 429))) {
        setError(reason.code === "INVALID_TOTP" ? "That code didn’t match. Enter a current authenticator code." : stagingError(reason, "Authenticator verification is temporarily limited."));
        return;
      }
      setPendingValues(undefined);
      if (reason instanceof AuthError) {
        setRevisionConflict(reason.code === "TRADE_CONTROLS_REVISION_CONFLICT");
        const fieldErrors = tradeControlFieldErrors(reason);
        setErrors(Object.fromEntries(tradeControlFields.flatMap((field) => fieldErrors[field] ?
          [[field, `The server requires ${range(field, fieldErrors[field])}.`]] : [])));
      }
      setError(stagingError(reason, "Paper Trade Controls could not be saved. Refresh to check the current settings."));
    } finally {
      writing.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <form className="space-y-4" onSubmit={(event) => void submit(event)} noValidate>
    <p className="text-xs text-muted-foreground">Revision {settings.revision} · {settings.updatedAt ? formatSnapshotDate(settings.updatedAt) : "Server defaults"}</p>
    <fieldset disabled={busy || engineRunning || !!pendingValues || revisionConflict} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {tradeControlFields.map((field) => {
        const { label, scale, blank } = fields[field];
        const bound = settings.bounds[field];
        const value = settings.controls[field];
        return <div key={field} className="min-w-0 space-y-1">
          <Label htmlFor={field}>{label}</Label>
          <Input id={field} name={field} inputMode={scale === 1 ? "numeric" : "decimal"} defaultValue={value === null ? "" : value / scale}
            placeholder={bound.nullable ? blank : undefined} aria-invalid={!!errors[field]} aria-describedby={`${field}-hint`} />
          <p id={`${field}-hint`} className={errors[field] ? "text-xs text-negative" : "text-xs text-muted-foreground"}>
            {errors[field] ?? range(field, bound)}{field === "maxConsecutiveLosses" && " · 0 turns this off"}
          </p>
        </div>;
      })}
    </fieldset>
    {pendingValues && <div className="max-w-64 space-y-1">
      <Label htmlFor="trade-controls-code">Authenticator code</Label>
      <Input id="trade-controls-code" ref={codeField} value={code} onChange={(event) => setCode(event.target.value)}
        inputMode="numeric" autoComplete="one-time-code" maxLength={6} readOnly={busy} />
    </div>}
    {error && <p role="alert" className="text-sm text-negative">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" disabled={busy || engineRunning || revisionConflict}>
        {busy ? "Saving…" : pendingValues ? "Verify and save" : "Save paper limits"}
      </Button>
      {pendingValues && <Button type="button" variant="outline" disabled={busy} onClick={() => {
        setPendingValues(undefined); setCode(""); setError("");
      }}>Cancel verification</Button>}
      {revisionConflict && <Button type="button" variant="outline" onClick={onReload}>Load latest saved limits</Button>}
    </div>
  </form>;
}
