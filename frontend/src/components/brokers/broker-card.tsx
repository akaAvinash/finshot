"use client";

import { useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link2, RefreshCw, ShieldCheck, Unplug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Status } from "@/components/ui/status";
import type { BrokerAction, BrokerConnection, BrokerId, BrokerStatus } from "@/lib/api/broker-types";
import { brokerNames, brokerScopeNames, formatBrokerTime, getBrokerStatus } from "@/lib/brokers";
import { cn } from "@/lib/utils";

const statusContent = {
  connected: { label: "Connected", health: "Healthy", tone: "positive" },
  expired: { label: "Session expired", health: "Reconnect required", tone: "accent" },
  disconnected: { label: "Disconnected", health: "Unavailable", tone: "neutral" },
} as const satisfies Record<BrokerStatus, { label: string; health: string; tone: "positive" | "accent" | "neutral" }>;

const dialogContent = {
  connect: { title: "Connect", button: "Connect demo account" },
  reconnect: { title: "Reconnect", button: "Reconnect demo account" },
  disconnect: { title: "Disconnect", button: "Disconnect demo account" },
};

type ConfirmedAction = keyof typeof dialogContent;

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm font-medium tabular-nums">{children}</dd>
    </div>
  );
}

export function BrokerCard({ connection, asOf, disabled, pending, onAction, actionError }: {
  connection: BrokerConnection;
  asOf: string;
  disabled: boolean;
  pending: boolean;
  onAction: (provider: BrokerId, action: BrokerAction) => Promise<boolean>;
  actionError?: { action: BrokerAction; message: string };
}) {
  const { provider, account } = connection;
  const name = brokerNames[provider];
  const status = getBrokerStatus(account, asOf);
  const copy = statusContent[status];
  const [intent, setIntent] = useState<ConfirmedAction | null>(null);
  const [failed, setFailed] = useState(false);
  const title = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const actionCompleted = useRef(false);
  const headingId = `broker-heading-${provider}`;
  const confirm = intent ? dialogContent[intent] : null;

  function openAction(event: MouseEvent<HTMLButtonElement>, action: ConfirmedAction) {
    opener.current = event.currentTarget;
    actionCompleted.current = false;
    setFailed(false);
    setIntent(action);
  }

  return (
    <Card aria-labelledby={headingId} className="flex flex-col overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 sm:p-5">
        <div className="flex items-center gap-3">
          <span aria-hidden className={cn("grid size-11 shrink-0 place-items-center rounded-xl border text-lg font-semibold",
            provider === "zerodha" ? "border-primary/25 bg-primary/12 text-accent-foreground" : "border-border bg-surface-raised text-foreground")}>
            {name[0]}
          </span>
          <div>
            <h2 id={headingId} ref={title} tabIndex={-1} className="text-lg font-semibold tracking-tight">{name}</h2>
            <p className="text-xs text-muted-foreground">Demo broker account</p>
          </div>
        </div>
        <Status tone={copy.tone} dot>{copy.label}</Status>
      </header>

      <div className="flex-1 space-y-4 p-4 sm:p-5">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-4">
          <Detail label="Account ID">
            {account ? <>
              <span aria-hidden>{account.maskedAccountId}</span>
              <span className="sr-only">Account ending in {account.maskedAccountId.slice(-4)}</span>
            </> : "Unavailable"}
          </Detail>
          <Detail label="Connection health">{copy.health}</Detail>
          <Detail label="Last account sync">{account?.lastSyncedAt ? <time dateTime={account.lastSyncedAt}>{formatBrokerTime(account.lastSyncedAt)}</time> : "Not synced"}</Detail>
          <Detail label="Session expiry">{account ? <time dateTime={account.expiresAt}>{formatBrokerTime(account.expiresAt)}</time> : "Unavailable"}</Detail>
        </dl>

        <div className="rounded-lg border border-border bg-background/55 p-3">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <ShieldCheck aria-hidden className="size-4 text-accent-foreground" /> Demo permissions
          </h3>
          {account ? (
            <ul aria-label="Demo permissions" className="mt-2 flex flex-wrap gap-1.5">
              {account.scopes.map((scope) => <li key={scope}><Status>{brokerScopeNames[scope]}</Status></li>)}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground">Connect a demo account to view its permissions.</p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-t border-border p-4 sm:px-5">
        {status === "connected" ? (
          <Button className="h-11" aria-label="Sync demo account" disabled={disabled} onClick={() => void onAction(provider, "sync")}>
            <RefreshCw aria-hidden className={pending ? "motion-safe:animate-spin" : undefined} /> Sync demo
          </Button>
        ) : (
          <Button className="h-11" disabled={disabled} onClick={(event) => openAction(event, status === "expired" ? "reconnect" : "connect")}>
            <Link2 aria-hidden /> {status === "expired" ? "Reconnect demo" : "Connect demo"}
          </Button>
        )}
        {account && <Button variant="outline" className="h-11" disabled={disabled} onClick={(event) => openAction(event, "disconnect")}>
          <Unplug aria-hidden /> Disconnect
        </Button>}
      </div>

      <Dialog open={intent !== null} onOpenChange={(open) => {
        if (!open && !pending) setIntent(null);
      }}>
        {intent && confirm && (
          <DialogContent onCloseAutoFocus={(event) => {
            event.preventDefault();
            const trigger = opener.current;
            if (!actionCompleted.current && trigger?.isConnected && !trigger.disabled) trigger.focus();
            else title.current?.focus();
          }}>
            <DialogTitle>{confirm.title} {name} demo?</DialogTitle>
            <DialogDescription>
              {intent === "disconnect"
                ? "This removes the sample connection from this preview. The activity log remains available."
                : "This creates a simulated connection with read-only demo permissions. No broker sign-in or credentials are needed."}
            </DialogDescription>
            {failed && <p role="alert" className="mt-3 text-sm text-negative">{actionError?.action === intent ? actionError.message : "The demo action did not complete. Try again."}</p>}
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Button variant="outline" className="h-11" disabled={pending} onClick={() => setIntent(null)}>Cancel</Button>
              <Button variant={intent === "disconnect" ? "outline" : "default"}
                className={cn("h-11", intent === "disconnect" && "border-negative/40 text-negative")}
                disabled={disabled} onClick={async () => {
                  if (await onAction(provider, intent)) {
                    actionCompleted.current = true;
                    setIntent(null);
                  } else setFailed(true);
                }}>{confirm.button}</Button>
            </div>
          </DialogContent>
        )}
      </Dialog>
    </Card>
  );
}
