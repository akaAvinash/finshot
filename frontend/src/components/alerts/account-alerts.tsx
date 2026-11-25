"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { acknowledgeInboxAlert, AlertRequestError, listInbox } from "@/lib/api/alerts-client";
import type { InboxPage, InboxSource } from "@/lib/api/alerts-types";
import { formatWorkspaceTime } from "@/lib/workspace-controls";
import { AlertInbox, AlertTotals, defaultAlertFilters, type AlertFilters } from "./alert-inbox";
import { AccountAlertPreferences } from "./account-alert-preferences";

const sources = { paper: "Paper trading", brokers: "Brokers", agents: "Agents", security: "Account security" } satisfies Record<InboxSource, string>;
const timezone = "Asia/Kolkata";

type InboxRequest = { filters: AlertFilters; cursors: Array<string | null>; focusId?: string };
type InboxResult = { request: InboxRequest; data?: InboxPage; error?: number };

export function AccountAlerts() {
  const [request, setRequest] = useState<InboxRequest>({ filters: defaultAlertFilters, cursors: [null] });
  const [loaded, setLoaded] = useState<InboxResult>();
  const [acknowledging, setAcknowledging] = useState(false);
  const [actionError, setActionError] = useState<number | null>(null);
  const notify = useNotification();
  const result = loaded?.request === request ? loaded : undefined;
  const { data } = result ?? {};
  const pageNumber = request.cursors.length;

  useEffect(() => {
    const controller = new AbortController();
    listInbox(request.filters, request.cursors.at(-1) ?? null, controller.signal).then((data) => {
      if (!controller.signal.aborted) setLoaded({ request, data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setLoaded({ request, error: error instanceof AlertRequestError ? error.status : 503 });
    });
    return () => controller.abort();
  }, [request]);

  useEffect(() => {
    if (!result || !request.focusId) return;
    const target = document.getElementById(`alert-${request.focusId}`) ?? document.getElementById("alert-inbox");
    target?.focus();
  }, [request.focusId, result]);

  function updateFilters(filters: AlertFilters) {
    setActionError(null);
    setRequest({ filters, cursors: [null] });
  }

  function refresh() {
    setActionError(null);
    setRequest((current) => ({ filters: current.filters, cursors: [null] }));
  }

  async function acknowledge(id: string) {
    if (acknowledging) return;
    setAcknowledging(true);
    setActionError(null);
    try {
      await acknowledgeInboxAlert(id);
      setRequest((current) => ({ ...current, focusId: current === request ? id : undefined }));
      notify("Alert acknowledged");
    } catch (error) {
      setActionError(error instanceof AlertRequestError ? error.status : 503);
    } finally {
      setAcknowledging(false);
    }
  }

  const rows = data?.items.map((item) => ({ ...item, description: item.message }));
  const next = data?.nextCursor;
  const showPagination = pageNumber > 1 || next || (!result && loaded && (loaded.request.cursors.length > 1 || loaded.data?.nextCursor));
  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Alerts" description="Review paper trading, broker, agent, and account notices." actions={
      <div className="flex flex-wrap items-center gap-2"><Status tone="accent" dot>Account inbox</Status>
        <Button variant="outline" onClick={refresh}><RefreshCw aria-hidden /> Refresh inbox</Button>
      </div>
    } />
    {data && <>
      <p className="border-t border-border pt-3 text-xs text-muted-foreground">As of <time dateTime={data.asOf}>{formatWorkspaceTime(data.asOf, timezone)}</time></p>
      <AlertTotals total={data.unread.total} critical={data.unread.critical} label="Account inbox summary" />
    </>}
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
      <AlertInbox filters={request.filters} onFilter={updateFilters} sources={sources} rows={rows} timezone={timezone}
        busy={acknowledging} onAcknowledge={(id) => void acknowledge(id)}
        error={actionError === 401 ? <Link href="/login" className="underline">Sign in again to acknowledge alerts.</Link> :
          actionError ? "This alert could not be acknowledged. Refresh the inbox or try again." : undefined}
        footer={showPagination && <footer className="flex items-center justify-between gap-2 border-t border-border p-3">
          <span className="text-xs text-muted-foreground" aria-live="polite">Page {pageNumber}</span>
          <div className="flex gap-1">
            <Button variant="ghost" size="icon" aria-label="Previous alerts page" aria-disabled={pageNumber === 1}
              className="aria-disabled:opacity-50" onClick={() => {
                if (pageNumber > 1) setRequest({ filters: request.filters, cursors: request.cursors.slice(0, -1) });
              }}><ChevronLeft aria-hidden /></Button>
            <Button variant="ghost" size="icon" aria-label="Next alerts page" aria-disabled={!next}
              className="aria-disabled:opacity-50" onClick={() => {
                if (next) setRequest({ filters: request.filters, cursors: [...request.cursors, next] });
              }}><ChevronRight aria-hidden /></Button>
          </div>
        </footer>}>
        {!result && <p role="status" className="p-5 text-sm text-muted-foreground">Loading alerts…</p>}
        {result?.error && <div role="alert" className="space-y-3 p-5 text-sm text-negative">
          <p>{result.error === 401 ? "Your session has expired." : result.error === 400 && pageNumber > 1 ?
            "This page is no longer current. Refresh the inbox to start again." : "The inbox could not load."}</p>
          {result.error === 401 ? <Button asChild variant="outline"><Link href="/login">Sign in again</Link></Button> :
            <Button variant="outline" onClick={refresh}>Retry alerts</Button>}
        </div>}
      </AlertInbox>
      <AccountAlertPreferences onSaved={refresh} />
    </div>
  </div>;
}
