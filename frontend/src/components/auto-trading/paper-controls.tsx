"use client";

import { useRef, useState } from "react";
import { CircleStop, FlaskConical, LockKeyhole, Play, Pause, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import type { PaperEngineCommand, PaperSnapshot } from "@/lib/api/auto-trading-types";

const engineLabel = { idle: "Idle", running: "Running", halted: "Halted" } as const;

function PanelTitle({ icon: Icon, children }: { icon: typeof Workflow; children: React.ReactNode }) {
  return <h2 className="flex items-center gap-2 font-semibold tracking-tight"><Icon aria-hidden className="size-4 text-accent-foreground" />{children}</h2>;
}

function KillSwitch({ disabled, pending, orders, onRun, focusAfterHalt, error }: {
  disabled: boolean;
  pending: boolean;
  orders: number;
  onRun: (command: PaperEngineCommand) => Promise<boolean>;
  focusAfterHalt: () => boolean;
  error?: string;
}) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [failed, setFailed] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(next) => {
      if (pending) return;
      if (next) {
        setConfirmation("");
        setFailed(false);
      }
      setOpen(next);
    }}>
      <DialogTrigger asChild>
        <Button disabled={disabled} variant="outline" className="h-11 border-negative/40 text-negative hover:text-negative"><CircleStop aria-hidden /> Paper kill switch</Button>
      </DialogTrigger>
      <DialogContent onCloseAutoFocus={(event) => {
        if (focusAfterHalt()) event.preventDefault();
      }}>
        <DialogTitle>Halt paper trading?</DialogTitle>
        <DialogDescription>
          This stops the simulated engine and cancels {orders} pending paper {orders === 1 ? "order" : "orders"}.
          Completed paper trades remain in the log.
        </DialogDescription>
        <form className="mt-5 space-y-3" onSubmit={async (event) => {
          event.preventDefault();
          if (confirmation.trim() !== "STOP") return;
          setFailed(false);
          if (await onRun({ action: "halt", confirmation: "STOP" })) setOpen(false);
          else setFailed(true);
        }}>
          <Label htmlFor="confirm-paper-halt" className="block">Type STOP to confirm</Label>
          <Input id="confirm-paper-halt" value={confirmation} onChange={({ target }) => setConfirmation(target.value)}
            autoComplete="off" maxLength={4} disabled={pending} />
          {failed && error && <p role="alert" className="text-sm text-negative">{error}</p>}
          <Button type="submit" variant="outline" className="h-11 w-full border-negative/40 text-negative"
            disabled={disabled || confirmation.trim() !== "STOP"}>Confirm paper halt</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PaperControls({ snapshot, stale, pending, onRun, canStart, finished, haltError }: {
  snapshot: Pick<PaperSnapshot, "engine" | "strategyId" | "strategies" | "agent" | "orders">;
  stale: boolean;
  pending: boolean;
  onRun: (command: PaperEngineCommand) => Promise<boolean>;
  canStart: boolean;
  finished?: boolean;
  haltError?: string;
}) {
  const { engine, strategyId, strategies, agent, orders } = snapshot;
  const disabled = stale || pending;
  const queued = orders.filter(({ status }) => status === "queued" || status === "held").length;
  const clearHaltButton = useRef<HTMLButtonElement>(null);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card aria-label="Paper engine" className="p-4 sm:p-5">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <PanelTitle icon={Workflow}>Paper engine</PanelTitle>
          <Status tone={engine === "halted" ? "negative" : engine === "running" ? "positive" : "neutral"} dot>{engineLabel[engine]}</Status>
        </header>
        <div className="my-4">
          <Status><LockKeyhole aria-hidden className="size-3.5" /> Live trading unavailable</Status>
        </div>
        <div className="flex flex-wrap gap-2">
          {engine === "halted" ? (
            <Button ref={clearHaltButton} variant="outline" className="h-11" disabled={disabled} onClick={() => void onRun({ action: "reset" })}>Clear paper halt</Button>
          ) : engine === "running" ? (
            <Button variant="outline" className="h-11" disabled={disabled} onClick={() => void onRun({ action: "pause" })}><Pause aria-hidden /> Pause paper engine</Button>
          ) : (
            <Button className="h-11" disabled={disabled || !canStart} onClick={() => void onRun({ action: "start" })}><Play aria-hidden /> Start paper engine</Button>
          )}
          <KillSwitch disabled={disabled || engine === "halted"} pending={pending} orders={queued} onRun={onRun} error={haltError}
            focusAfterHalt={() => {
              if (!clearHaltButton.current) return false;
              clearHaltButton.current.focus();
              return true;
            }} />
        </div>
        {engine === "halted" && <p className="mt-3 text-sm text-muted-foreground">Clear the halt before starting a new paper run.</p>}
      </Card>

      <Card aria-label="Strategy and agent" className="p-4 sm:p-5">
        <PanelTitle icon={FlaskConical}>Strategy and agent</PanelTitle>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="text-muted-foreground">{agent.name}</span>
          <Status tone={agent.ready ? "positive" : "neutral"} dot>{agent.ready ? "Demo ready" : "Unavailable"}</Status>
        </div>
        <div className="mt-4 space-y-2">
          <Label htmlFor="paper-strategy">Assigned strategy</Label>
          <select id="paper-strategy" value={strategyId ?? ""} disabled={disabled || engine !== "idle"}
            onChange={(event) => void onRun({ action: "assign", strategyId: event.target.value })}
            className="block h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground disabled:opacity-60">
            <option value="" disabled>Select a strategy</option>
            {strategies.map(({ id, name, instrument }) => <option key={id} value={id}>{name} · {instrument}</option>)}
          </select>
          <p className="text-xs text-muted-foreground">Strategy can change while the paper engine is idle.</p>
          {finished && strategyId && strategies.some(({ id }) => id === strategyId) &&
            <Button variant="outline" disabled={disabled || engine !== "idle"} onClick={() => void onRun({ action: "assign", strategyId })}>Prepare another replay</Button>}
        </div>
      </Card>

    </div>
  );
}
