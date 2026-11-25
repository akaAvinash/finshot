"use client";

import type { ReactNode } from "react";
import { Bell, Check, CircleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { alertSeverities, type WorkspaceAlert, type WorkspaceTimezone } from "@/lib/api/workspace-controls-types";
import { alertSeverityLabels, formatWorkspaceTime } from "@/lib/workspace-controls";

export type AlertFilters = { status: "all" | "unread"; severity: string; source: string };
export const defaultAlertFilters: AlertFilters = { status: "all", severity: "all", source: "all" };

const tones = { critical: "negative", warning: "accent", info: "neutral" } as const;
const selectClass = "h-11 min-w-0 rounded-lg border border-input bg-background px-3 text-sm";
type AlertRow = Omit<WorkspaceAlert, "source"> & { source: string };

export function AlertTotals({ total, critical, label }: { total: number; critical: number; label: string }) {
  return <dl className="grid grid-cols-2 gap-3" aria-label={label}>
    <div className="rounded-xl border border-border bg-card p-3.5 sm:p-4"><dt className="flex items-center gap-2 text-xs text-muted-foreground"><Bell aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Unread alerts</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{total}</dd></div>
    <div className="rounded-xl border border-border bg-card p-3.5 sm:p-4"><dt className="flex items-center gap-2 text-xs text-muted-foreground"><CircleAlert aria-hidden className="size-4 shrink-0 text-negative" /> Unread critical</dt><dd className="mt-1 text-2xl font-semibold tabular-nums text-negative">{critical}</dd></div>
  </dl>;
}

export function AlertInbox({ filters, sources, rows, timezone, disabled, busy, error, children, footer, onFilter, onAcknowledge }: {
  filters: AlertFilters;
  sources: Readonly<Record<string, string>>;
  rows?: readonly AlertRow[];
  timezone: WorkspaceTimezone;
  disabled?: boolean;
  busy?: boolean;
  error?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  onFilter: (filters: AlertFilters) => void;
  onAcknowledge: (id: string) => void;
}) {
  return <Card aria-labelledby="alert-inbox" className="overflow-hidden">
    <header className="space-y-3 border-b border-border p-4 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="alert-inbox" tabIndex={-1} className="font-semibold">Alert inbox</h2>
        <div role="group" aria-label="Alert read status" className="flex gap-1 rounded-lg border border-border bg-background p-0.5">
          <Button size="sm" className="h-9" variant={filters.status === "all" ? "default" : "ghost"} aria-pressed={filters.status === "all"}
            onClick={() => onFilter({ ...filters, status: "all" })}>All alerts</Button>
          <Button size="sm" className="h-9" variant={filters.status === "unread" ? "default" : "ghost"} aria-pressed={filters.status === "unread"}
            onClick={() => onFilter({ ...filters, status: "unread" })}>Unread</Button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:flex">
        <Label htmlFor="alert-severity" className="sr-only">Filter alerts by severity</Label>
        <select id="alert-severity" className={selectClass} value={filters.severity} onChange={({ target }) => onFilter({ ...filters, severity: target.value })}>
          <option value="all">Any severity</option>{alertSeverities.map((value) => <option key={value} value={value}>{alertSeverityLabels[value]}</option>)}
        </select>
        <Label htmlFor="alert-source" className="sr-only">Filter alerts by source</Label>
        <select id="alert-source" className={selectClass} value={filters.source} onChange={({ target }) => onFilter({ ...filters, source: target.value })}>
          <option value="all">All sources</option>{Object.entries(sources).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
    </header>
    {rows ? rows.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No alerts match this view.</p> : <ol className="divide-y divide-border">
      {rows.map((alert) => <li key={alert.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-4 sm:px-5">
        <div className="min-w-0 flex-1 basis-64">
          <div className="flex flex-wrap items-center gap-2">
            <Status tone={tones[alert.severity]} dot>{alertSeverityLabels[alert.severity]}</Status>
            <span className="text-xs text-muted-foreground">{sources[alert.source]} · <time dateTime={alert.createdAt}>{formatWorkspaceTime(alert.createdAt, timezone)}</time></span>
          </div>
          <h3 id={`alert-${alert.id}`} tabIndex={-1} className="mt-2 text-sm font-semibold wrap-anywhere">{alert.title}</h3>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground wrap-anywhere">{alert.description}</p>
        </div>
        {alert.acknowledgedAt ? <Status><Check aria-hidden className="size-3" /> Acknowledged</Status> : <Button variant="outline" className="h-10 aria-disabled:opacity-50"
          disabled={disabled} aria-disabled={busy} aria-label={`Acknowledge ${alert.title}`} onClick={() => { if (!busy) onAcknowledge(alert.id); }}>Acknowledge</Button>}
      </li>)}
    </ol> : children}
    {footer}
  </Card>;
}
