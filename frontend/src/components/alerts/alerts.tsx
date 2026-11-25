"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Clock3, LockKeyhole, Settings2 } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { useWorkspacePreview } from "@/components/use-workspace-preview";
import { useWorkspaceControls } from "@/components/workspace-controls-provider";
import { WorkspacePreviewSelect } from "@/components/workspace-preview-select";
import type { NotificationPreferences } from "@/lib/api/workspace-controls-types";
import { alertSourceLabels, formatWorkspaceTime } from "@/lib/workspace-controls";
import { AlertInbox, AlertTotals, defaultAlertFilters } from "./alert-inbox";

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
  const [filters, setFilters] = useState(defaultAlertFilters);
  const [acknowledgedId, setAcknowledgedId] = useState<string | null>(null);
  const notify = useNotification();
  const { result } = preview;
  const data = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;
  const unread = data?.alerts.filter((alert) => alert.acknowledgedAt === null) ?? [];
  const critical = unread.filter((alert) => alert.severity === "critical");
  const visible = data?.alerts.filter((alert) => (filters.status === "all" || alert.acknowledgedAt === null) &&
    (filters.severity === "all" || alert.severity === filters.severity) && (filters.source === "all" || alert.source === filters.source)) ?? [];

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
      <AlertTotals total={unread.length} critical={critical.length} label="Demo inbox summary" />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <AlertInbox filters={filters} onFilter={setFilters} sources={alertSourceLabels} rows={visible} timezone={data.timezone}
          disabled={result?.status !== "ready" || preview.busy} error={preview.actionError} onAcknowledge={(id) => void acknowledge(id)} />
        <DeliveryPreferences notifications={data.notifications} />
      </div>
    </>}
  </div>;
}
