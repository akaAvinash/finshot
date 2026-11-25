import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Archive, History, Plug, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { retentionOptions, type SensitiveSettingsChange, type SettingsSnapshot } from "@/lib/api/workspace-controls-types";
import { formatInr } from "@/lib/format";
import { formatWorkspaceTime, maxDemoLossPaise, maxDemoTrades, settingsActions, validateDemoRisk } from "@/lib/workspace-controls";
import { SettingsCard } from "./settings-preferences";

export type RequestConfirmation = (change: SensitiveSettingsChange, opener: HTMLElement) => void;

export function SecuritySettings({ snapshot, disabled, onConfirm }: {
  snapshot: SettingsSnapshot;
  disabled: boolean;
  onConfirm: RequestConfirmation;
}) {
  return <SettingsCard id="security-settings" title="Security and sessions" description="Inspect a masked sample phone and demo sessions. Changes here affect only the preview." icon={ShieldCheck}>
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-background/45 p-3">
      <div><p className="text-xs text-muted-foreground">Sample phone</p><p className="mt-1 text-sm font-medium tabular-nums">{snapshot.maskedPhone}</p></div>
      {snapshot.phoneVerified ? <Status tone="positive" dot>Demo verified</Status> : <Button variant="outline" className="h-10" disabled={disabled}
        onClick={(event) => onConfirm({ kind: "verify-phone" }, event.currentTarget)}>Verify sample phone</Button>}
    </div>
    <ul aria-label="Sample sessions" className="mt-3 space-y-2">
      {snapshot.sessions.map((session) => <li key={session.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
        <div><p className="text-sm font-medium">{session.name}</p><p className="mt-1 text-xs text-muted-foreground">{session.revokedAt ? "Revoked" : "Last seen"} · <time dateTime={session.revokedAt ?? session.lastSeenAt}>{formatWorkspaceTime(session.revokedAt ?? session.lastSeenAt, snapshot.timezone)}</time></p></div>
        {session.current ? <Status tone="positive" dot>Current sample</Status> : session.revokedAt ? <Status>Revoked</Status> : <Button variant="outline" className="h-10" disabled={disabled}
          aria-label={`Revoke ${session.name}`} onClick={(event) => onConfirm({ kind: "revoke-session", sessionId: session.id }, event.currentTarget)}>Revoke demo</Button>}
      </li>)}
    </ul>
  </SettingsCard>;
}

export function RiskSettings({ snapshot, disabled, onConfirm }: {
  snapshot: SettingsSnapshot;
  disabled: boolean;
  onConfirm: RequestConfirmation;
}) {
  const [validation, setValidation] = useState<string | null>(null);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const risk = { dailyLossPaise: Math.round(Number(values.get("dailyLoss")) * 100), maxTrades: Number(values.get("maxTrades")) };
    const error = validateDemoRisk(risk);
    setValidation(error);
    const opener = event.currentTarget.querySelector("button[type=submit]");
    if (!error && opener instanceof HTMLElement) onConfirm({ kind: "set-risk", risk }, opener);
  }

  return <SettingsCard id="risk-settings" title="Demo risk limits" description="Preview validation and confirmation. These sample values have no effect on the paper engine or live orders." icon={SlidersHorizontal}>
    <form onSubmit={save}>
      <fieldset disabled={disabled} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="min-w-0 space-y-1.5"><Label htmlFor="settings-daily-loss">Daily loss limit (INR)</Label>
            <Input id="settings-daily-loss" name="dailyLoss" type="number" min={1} max={maxDemoLossPaise / 100} step="0.01" defaultValue={snapshot.risk.dailyLossPaise / 100} required />
          </div>
          <div className="min-w-0 space-y-1.5"><Label htmlFor="settings-max-trades">Max trades per day</Label>
            <Input id="settings-max-trades" name="maxTrades" type="number" min={1} max={maxDemoTrades} step="1" defaultValue={snapshot.risk.maxTrades} required />
          </div>
        </div>
        {validation && <p role="alert" className="text-sm text-negative">{validation}</p>}
        <Button type="submit" variant="outline" className="h-11">Review risk changes</Button>
      </fieldset>
    </form>
  </SettingsCard>;
}

export function RetentionSettings({ snapshot, disabled, onConfirm }: {
  snapshot: SettingsSnapshot;
  disabled: boolean;
  onConfirm: RequestConfirmation;
}) {
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = Number(new FormData(event.currentTarget).get("retention"));
    const days = retentionOptions.find((option) => option === value);
    const opener = event.currentTarget.querySelector("button[type=submit]");
    if (days && opener instanceof HTMLElement) onConfirm({ kind: "set-retention", days }, opener);
  }

  return <SettingsCard id="retention-settings" title="Data retention" description="Preview a retention preference for sample activity. Saving a choice deletes no records." icon={Archive}>
    <form onSubmit={save}>
      <fieldset disabled={disabled} className="flex flex-wrap items-end gap-2">
        <div className="min-w-28 flex-1 space-y-1.5"><Label htmlFor="settings-retention">Demo retention</Label>
          <select id="settings-retention" name="retention" defaultValue={snapshot.retentionDays} className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm">
            {retentionOptions.map((days) => <option key={days} value={days}>{days} days</option>)}
          </select>
        </div>
        <Button type="submit" variant="outline" className="h-11">Review retention</Button>
      </fieldset>
    </form>
  </SettingsCard>;
}

export function SettingsAudit({ snapshot }: { snapshot: SettingsSnapshot }) {
  return <SettingsCard id="settings-audit" title="Recent settings changes" description="Changes recorded during this demo visit. Verification codes are omitted." icon={History}>
    {snapshot.audit.length === 0 ? <p className="text-sm text-muted-foreground">No settings changes during this visit.</p> : <ol className="max-h-54 divide-y divide-border overflow-y-auto" aria-label="Demo settings audit trail">
      {snapshot.audit.map((entry) => <li key={entry.id} className="flex flex-wrap justify-between gap-2 py-2.5 text-sm"><span>{settingsActions[entry.action]}</span><time className="text-xs text-muted-foreground" dateTime={entry.at}>{formatWorkspaceTime(entry.at, snapshot.timezone)}</time></li>)}
    </ol>}
  </SettingsCard>;
}

export function BrokerSettingsLink() {
  return <SettingsCard id="broker-settings" title="Broker management" description="Inspect or reconnect demo broker accounts from the Brokers workspace." icon={Plug}>
    <Button asChild variant="outline" className="h-11"><Link href="/brokers">Open Brokers</Link></Button>
  </SettingsCard>;
}

export function describeRisk(snapshot: SettingsSnapshot["risk"]) {
  return `${formatInr(snapshot.dailyLossPaise / 100)} daily loss limit and ${snapshot.maxTrades} trades per day.`;
}
