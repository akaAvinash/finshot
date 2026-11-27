"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import {
  demoAuthorizationPath, getBrokerConnections, sendBrokerConnectionAction, startBrokerAuthorization,
  type BrokerAuthorizationStart, type BrokerConnectionsSnapshot,
} from "@/lib/api/broker-connections-client";
import { isUnconfirmedStagingWrite, stagingError } from "@/lib/api/staging-client";
import { AuthError, verifyAccountStepUp } from "@/lib/auth/browser-client";
import { formatBrokerTime } from "@/lib/brokers";
import { BrokerPortfolioPanel } from "./broker-portfolio";

type Intent = { kind: "authorize"; label: string; selection: BrokerAuthorizationStart } |
  { kind: "sync" | "disconnect"; label: string; connectionId: string };
const verbs = { authorize: "Authorize", sync: "Sync", disconnect: "Disconnect" } as const;
const events = { connect: "Connected", reconnect: "Reauthorized", sync: "Synced", disconnect: "Disconnected", expire: "Expired" } as const;

export function BrokerConnections() {
  const [snapshot, setSnapshot] = useState<BrokerConnectionsSnapshot>();
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [intent, setIntent] = useState<Intent>();
  const [portfolio, setPortfolio] = useState<string>();
  const [portfolioRevision, setPortfolioRevision] = useState(0);
  const opener = useRef<HTMLButtonElement>(null);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const reading = useRef<AbortController | null>(null);
  const notify = useNotification();
  useEffect(() => {
    const controller = new AbortController();
    reading.current = controller;
    void getBrokerConnections(controller.signal).then((data) => {
      if (!controller.signal.aborted) { setSnapshot(data); setError(""); }
    }, (error: unknown) => {
      if (!controller.signal.aborted) setError(stagingError(error, "Broker connections could not load."));
    });
    return () => controller.abort();
  }, [refresh]);

  function reload(clearSnapshot = false) {
    reading.current?.abort();
    if (clearSnapshot) { setSnapshot(undefined); setError(""); }
    setRefresh((value) => value + 1);
  }

  function open(action: Intent, trigger: HTMLButtonElement) {
    opener.current = trigger;
    setIntent(action);
  }

  function updated(data: BrokerConnectionsSnapshot, action: "sync" | "disconnect") {
    reading.current?.abort();
    setError("");
    setSnapshot(data);
    setIntent(undefined);
    setPortfolioRevision((revision) => revision + 1);
    notify(action === "sync" ? "Demo account synced." : "Demo account disconnected.");
  }

  const selected = snapshot?.connections.find(({ connectionId }) => connectionId === portfolio);
  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Brokers" description="Authorize demo accounts, sync read-only data, and review connection activity."
      actions={<><Status tone="accent" dot>Demo connections</Status>
        <Button variant="outline" disabled={!!intent || (!snapshot && !error)} onClick={() => reload(true)}>Refresh brokers</Button></>} />
    {!snapshot && !error && <DashboardSkeleton label="Loading brokers" />}
    {error && <DataState error title="Brokers could not load" description={error} />}
    {snapshot && <>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <h2 ref={resultsHeading} tabIndex={-1} className="text-sm font-semibold text-foreground">Broker connections</h2>
        <time dateTime={snapshot.asOf}>Demo snapshot · {formatBrokerTime(snapshot.asOf)}</time>
      </div>
      {!snapshot.providers.length && <DataState title="No demo providers available" description="Refresh after a broker provider is enabled." />}
      <div className="grid gap-4 lg:grid-cols-2">
        {snapshot.providers.map((provider) => {
          const accounts = snapshot.connections.filter(({ providerId }) => providerId === provider.id);
          return <Card key={provider.id} aria-label={provider.displayName} className="min-w-0 space-y-3 p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold">{provider.displayName}</h3>
              <Status tone={provider.available ? "accent" : "neutral"}>{provider.available ? "Demo provider" : "Unavailable"}</Status>
            </div>
            <p className="text-xs text-muted-foreground">{accounts.length} / {provider.maxConnections} connections</p>
            <Button variant="outline" disabled={!!intent || !!error || !provider.available || accounts.length >= provider.maxConnections}
              onClick={(event) => open({ kind: "authorize", label: provider.displayName, selection: { providerId: provider.id } }, event.currentTarget)}>Connect demo</Button>
            {accounts.length > 0 && <ul className="space-y-2">
              {accounts.map((account) => <li key={account.connectionId} className="space-y-2 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium">{account.maskedAccountId}</span>
                  <Status tone={account.status === "connected" ? "positive" : "accent"} dot>{account.status === "connected" ? "Connected" : "Expired"}</Status>
                </div>
                <p className="text-xs text-muted-foreground">
                  Connected <time dateTime={account.connectedAt}>{formatBrokerTime(account.connectedAt)}</time> ·
                  {account.lastSyncedAt ? <> Last synced <time dateTime={account.lastSyncedAt}>{formatBrokerTime(account.lastSyncedAt)}</time></> : " Awaiting first sync"}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" disabled={!!intent || !!error || account.status !== "connected"}
                    onClick={(event) => open({ kind: "sync", label: account.maskedAccountId, connectionId: account.connectionId }, event.currentTarget)}>Sync demo</Button>
                  <Button size="sm" variant="outline" disabled={!!intent || !!error || !provider.available}
                    onClick={(event) => open({ kind: "authorize", label: account.maskedAccountId, selection: { connectionId: account.connectionId } }, event.currentTarget)}>Reauthorize</Button>
                  <Button size="sm" variant="outline" onClick={() => setPortfolio(account.connectionId)}>View portfolio</Button>
                  <Button size="sm" variant="ghost" disabled={!!intent || !!error}
                    onClick={(event) => open({ kind: "disconnect", label: account.maskedAccountId, connectionId: account.connectionId }, event.currentTarget)}>Disconnect</Button>
                </div>
              </li>)}
            </ul>}
          </Card>;
        })}
      </div>
      {selected && <BrokerPortfolioPanel key={`${selected.connectionId}:${portfolioRevision}`} connectionId={selected.connectionId}
        account={selected.maskedAccountId} onClose={() => setPortfolio(undefined)} />}
      <Card className="space-y-2 p-4 sm:p-5">
        <h2 className="font-semibold">Broker activity</h2>
        {snapshot.events.length ? <ul className="max-h-64 divide-y divide-border overflow-y-auto">
          {[...snapshot.events].reverse().map((event) => <li key={event.id} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
            <span>{snapshot.providers.find(({ id }) => id === event.providerId)?.displayName ?? event.providerId} · {events[event.action]}</span>
            <time className="text-xs text-muted-foreground" dateTime={event.at}>{formatBrokerTime(event.at)}</time>
          </li>)}
        </ul> : <p className="text-sm text-muted-foreground">No demo broker activity yet.</p>}
      </Card>
    </>}
    {intent && <BrokerActionDialog intent={intent} onClose={() => setIntent(undefined)} onUpdated={updated}
      onExpired={() => reload()} onUnconfirmed={() => reload(true)} restoreFocus={() => {
        if (opener.current?.isConnected && !opener.current.disabled) opener.current.focus();
        else resultsHeading.current?.focus();
      }} />}
  </div>;
}

function BrokerActionDialog({ intent, onClose, onUpdated, onExpired, onUnconfirmed, restoreFocus }: {
  intent: Intent; onClose: () => void; onUpdated: (value: BrokerConnectionsSnapshot, action: "sync" | "disconnect") => void;
  onExpired: () => void; onUnconfirmed: () => void; restoreFocus: () => void;
}) {
  const [stepUp, setStepUp] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const request = useRef<AbortController | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);
  useEffect(() => { if (stepUp) codeInput.current?.focus(); }, [stepUp]);
  useEffect(() => () => request.current?.abort(), []);

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (request.current || unconfirmed) return;
    if (stepUp && !/^\d{6}$/.test(code)) { setError("Enter the six-digit authenticator code."); return; }
    const controller = new AbortController();
    request.current = controller;
    setError("");
    setBusy(true);
    try {
      if (stepUp) await verifyAccountStepUp(code);
      if (controller.signal.aborted) return;
      if (intent.kind === "authorize") {
        const next = await startBrokerAuthorization(intent.selection, controller.signal);
        if (controller.signal.aborted) return;
        const destination = demoAuthorizationPath(next.authorizeUrl, window.location.origin);
        if (destination) window.location.assign(destination);
        else setError("The server returned an invalid demo authorization address.");
      } else {
        const data = await sendBrokerConnectionAction(intent.connectionId, intent.kind, controller.signal);
        if (!controller.signal.aborted) onUpdated(data, intent.kind);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setCode("");
      if (error instanceof AuthError && error.code === "STEP_UP_REQUIRED" && intent.kind === "authorize") { setStepUp(true); return; }
      if (intent.kind !== "authorize" && isUnconfirmedStagingWrite(error)) {
        setUnconfirmed(true);
        setError("The action could not be confirmed. Broker connections are refreshing. Close this dialog to check the account.");
        onUnconfirmed();
        return;
      }
      if (error instanceof AuthError && error.code === "BROKER_AUTH_EXPIRED") onExpired();
      setError(error instanceof AuthError && error.code === "INVALID_TOTP" ? "That code didn’t match. Try a current authenticator code." :
        stagingError(error, "The demo broker action could not be completed."));
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
    <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus(); }}>
      <DialogTitle>{verbs[intent.kind]} {intent.label}?</DialogTitle>
      <DialogDescription>{intent.kind === "authorize" ? "Continue to the demo approval page to grant read-only access." :
        intent.kind === "disconnect" ? "Remove this demo connection. Previous activity stays in the log." : "Refresh the stored read-only portfolio."}</DialogDescription>
      <form className="mt-4 space-y-3" onSubmit={(event) => void run(event)}>
        {stepUp && <div className="space-y-1">
          <Label htmlFor="broker-step-up-code">Authenticator code</Label>
          <Input id="broker-step-up-code" ref={codeInput} value={code} onChange={(event) => setCode(event.target.value)}
            inputMode="numeric" autoComplete="one-time-code" maxLength={6} readOnly={busy} />
        </div>}
        {error && <p role="alert" className="text-sm text-negative">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy || unconfirmed}>{busy ? "Working…" : stepUp ? "Verify and continue" : `${verbs[intent.kind]} demo account`}</Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>{unconfirmed ? "Close" : "Cancel"}</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>;
}
