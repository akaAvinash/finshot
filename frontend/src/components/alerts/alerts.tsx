"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bell, Check, CircleAlert, Clock3, LockKeyhole, Settings2 } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { useWorkspacePreview } from "@/components/use-workspace-preview";
import { useWorkspaceControls } from "@/components/workspace-controls-provider";
import { WorkspacePreviewSelect } from "@/components/workspace-preview-select";
import { alertSeverities, alertSources, type NotificationPreferences } from "@/lib/api/workspace-controls-types";
import { alertSeverityLabels, alertSourceLabels, formatWorkspaceTime } from "@/lib/workspace-controls";

const tones = { critical: "negative", warning: "accent", info: "neutral" } as const;
const selectClass = "h-11 min-w-0 rounded-lg border border-input bg-background px-3 text-sm";

function DeliveryPreferences({ notifications }: { notifications: NotificationPreferences }) {
  const channels = [
    { name: "Critical in-app alerts", value: "Always on" },
    { name: "Optional in-app updates", value: notifications.inAppUpdates ? "On" : "Off" },
    { name: "Email digest", value: notifications.emailDigest ? "Demo on" : "Off" },
    { name: "Critical SMS", value: notifications.criticalSms ? "Demo on" : "Off" },
  ];
  return <Card aria-labelledby="alert-delivery" className="p-4 sm:p-5">
    <h2 id="alert-delivery" className="flex items-center gap-2 font-semibold"><Settings2 aria-hidden className="size-4 text-accent-foreground" /> Delivery preferences</h2>
    <dl className="mt-3 divide-y divide-border">
      {channels.map(({ name, value }) => <div key={name} className="flex items-center justify-between gap-2 py-2.5">
        <dt className="text-sm">{name}</dt><dd><Status tone={value === "Off" ? "neutral" : "positive"}>{value}</Status></dd>
      </div>)}
    </dl>
    <p className="mt-3 text-xs leading-relaxed text-muted-foreground">Email and SMS preferences are simulated. The demo sends no notifications to external channels.</p>
    <Button asChild variant="outline" className="mt-4 h-11 w-full"><Link href="/settings#notification-preferences">Manage notifications</Link></Button>
  </Card>;
}

export function Alerts() {
  const client = useWorkspaceControls();
  const preview = useWorkspacePreview(client.getAlerts, client.acknowledgeAlert);
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [severity, setSeverity] = useState("all");
  const [source, setSource] = useState("all");
  const [acknowledgedId, setAcknowledgedId] = useState<string | null>(null);
  const notify = useNotification();
  const { result } = preview;
  const data = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;
  const unread = data?.alerts.filter((alert) => alert.acknowledgedAt === null) ?? [];
  const critical = unread.filter((alert) => alert.severity === "critical");
  const visible = data?.alerts.filter((alert) => (filter === "all" || alert.acknowledgedAt === null) &&
    (severity === "all" || alert.severity === severity) && (source === "all" || alert.source === source)) ?? [];

  useEffect(() => {
    if (!acknowledgedId) return;
    const target = document.getElementById(`alert-${acknowledgedId}`) ?? document.getElementById("alert-inbox");
    target?.focus();
  }, [acknowledgedId]);

  async function acknowledge(id: string) {
    if (await preview.run(id)) {
      setAcknowledgedId(id);
      notify("Demo alert acknowledged");
    }
  }

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Alerts" description="Review simulated risk, broker, market, paper trading, and account notices." actions={
      <div className="flex flex-wrap items-center gap-2"><Status tone="accent" dot>Demo inbox</Status>
        <WorkspacePreviewSelect label="Alerts preview data" scenario={preview.scenario} disabled={preview.busy} onChange={preview.load} />
      </div>
    } />
    {!result && <DashboardSkeleton label="Loading alerts" />}
    {result?.status === "empty" && <DataState title="No alerts yet" description="This demo snapshot has an empty inbox."
      action={<Button variant="outline" onClick={() => preview.load("ready")}>Load sample alerts</Button>} />}
    {result?.status === "denied" && <DataState title="Alerts access denied" description="This simulated session cannot read the inbox." icon={LockKeyhole}
      action={<Button variant="outline" onClick={() => preview.load("ready")}>Restore demo access</Button>} />}
    {result?.status === "error" && <DataState error title="Alerts could not load" description="The demo inbox request failed."
      action={<Button variant="outline" onClick={() => preview.load("ready")}>Retry alerts</Button>} />}

    {data && <>
      <p className="border-t border-border pt-3 text-xs text-muted-foreground">Sample snapshot · <time dateTime={data.asOf}>{formatWorkspaceTime(data.asOf, data.timezone)}</time></p>
      {result?.status === "stale" && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
        <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> The inbox is stale. Acknowledgement is paused.</p>
        <Button variant="outline" size="sm" onClick={() => preview.load("ready")}>Load latest alerts</Button>
      </div>}
      <dl className="grid grid-cols-2 gap-3" aria-label="Demo inbox summary">
        <div className="rounded-xl border border-border bg-card p-3.5 sm:p-4"><dt className="flex items-center gap-2 text-xs text-muted-foreground"><Bell aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Unread alerts</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{unread.length}</dd></div>
        <div className="rounded-xl border border-border bg-card p-3.5 sm:p-4"><dt className="flex items-center gap-2 text-xs text-muted-foreground"><CircleAlert aria-hidden className="size-4 shrink-0 text-negative" /> Unread critical</dt><dd className="mt-1 text-2xl font-semibold tabular-nums text-negative">{critical.length}</dd></div>
      </dl>
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <Card aria-labelledby="alert-inbox" className="overflow-hidden">
          <header className="space-y-3 border-b border-border p-4 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="alert-inbox" tabIndex={-1} className="font-semibold">Alert inbox</h2>
              <div role="group" aria-label="Alert read status" className="flex gap-1 rounded-lg border border-border bg-background p-0.5">
                <Button size="sm" className="h-9" variant={filter === "all" ? "default" : "ghost"} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All alerts</Button>
                <Button size="sm" className="h-9" variant={filter === "unread" ? "default" : "ghost"} aria-pressed={filter === "unread"} onClick={() => setFilter("unread")}>Unread</Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:flex">
              <Label htmlFor="alert-severity" className="sr-only">Filter alerts by severity</Label>
              <select id="alert-severity" className={selectClass} value={severity} onChange={({ target }) => setSeverity(target.value)}>
                <option value="all">Any severity</option>{alertSeverities.map((value) => <option key={value} value={value}>{alertSeverityLabels[value]}</option>)}
              </select>
              <Label htmlFor="alert-source" className="sr-only">Filter alerts by source</Label>
              <select id="alert-source" className={selectClass} value={source} onChange={({ target }) => setSource(target.value)}>
                <option value="all">All sources</option>{alertSources.map((value) => <option key={value} value={value}>{alertSourceLabels[value]}</option>)}
              </select>
            </div>
            {preview.actionError && <p role="alert" className="text-sm text-negative">{preview.actionError}</p>}
          </header>
          {visible.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No alerts match this view.</p> : <ol className="divide-y divide-border">
            {visible.map((alert) => <li key={alert.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-4 sm:px-5">
              <div className="min-w-0 flex-1 basis-64">
                <div className="flex flex-wrap items-center gap-2">
                  <Status tone={tones[alert.severity]} dot>{alertSeverityLabels[alert.severity]}</Status>
                  <span className="text-xs text-muted-foreground">{alertSourceLabels[alert.source]} · <time dateTime={alert.createdAt}>{formatWorkspaceTime(alert.createdAt, data.timezone)}</time></span>
                </div>
                <h3 id={`alert-${alert.id}`} tabIndex={-1} className="mt-2 text-sm font-semibold">{alert.title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{alert.description}</p>
              </div>
              {alert.acknowledgedAt ? <Status><Check aria-hidden className="size-3" /> Acknowledged</Status> : <Button variant="outline" className="h-10"
                disabled={result?.status !== "ready" || preview.busy} aria-label={`Acknowledge ${alert.title}`} onClick={() => void acknowledge(alert.id)}>Acknowledge</Button>}
            </li>)}
          </ol>}
        </Card>
        <DeliveryPreferences notifications={data.notifications} />
      </div>
    </>}
  </div>;
}
