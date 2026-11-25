"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Clock3, LockKeyhole } from "lucide-react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { useWorkspacePreview } from "@/components/use-workspace-preview";
import { useWorkspaceControls } from "@/components/workspace-controls-provider";
import { WorkspacePreviewSelect } from "@/components/workspace-preview-select";
import type { SensitiveSettingsChange, SettingsCommand } from "@/lib/api/workspace-controls-types";
import { formatWorkspaceTime, sampleSettingsCode, settingsActions } from "@/lib/workspace-controls";
import { NotificationSettings, ProfilePreferences } from "./settings-preferences";
import { BrokerSettingsLink, describeRisk, RetentionSettings, RiskSettings, SecuritySettings, SettingsAudit } from "./settings-security";

const confirmCopy = {
  "verify-phone": { title: "Confirm sample phone", anchor: "security-settings" },
  "revoke-session": { title: "Confirm sample session revocation", anchor: "security-settings" },
  "set-retention": { title: "Confirm retention preference", anchor: "retention-settings" },
  "set-risk": { title: "Confirm demo risk limits", anchor: "risk-settings" },
} as const;

export function Settings() {
  const client = useWorkspaceControls();
  const preview = useWorkspacePreview(client.getSettings, client.updateSettings);
  const [confirmation, setConfirmation] = useState<SensitiveSettingsChange | null>(null);
  const [focusAfterSave, setFocusAfterSave] = useState<{ kind: "set-profile" | "set-notifications" } | null>(null);
  const displayNameInput = useRef<HTMLInputElement>(null);
  const notificationSaveButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const fallback = useRef<string | null>(null);
  const notify = useNotification();
  const { result } = preview;
  const snapshot = result?.status === "ready" || result?.status === "stale" ? result.data : undefined;
  const hasSnapshot = snapshot !== undefined;
  const disabled = result?.status !== "ready" || preview.busy;

  useEffect(() => {
    if (hasSnapshot && window.location.hash === "#notification-preferences") {
      document.getElementById("notification-preferences")?.focus();
    }
  }, [hasSnapshot]);

  useEffect(() => {
    if (focusAfterSave?.kind === "set-profile") displayNameInput.current?.focus();
    if (focusAfterSave?.kind === "set-notifications") notificationSaveButton.current?.focus();
  }, [focusAfterSave]);

  function open(change: SensitiveSettingsChange, opener: HTMLElement) {
    returnFocus.current = opener;
    fallback.current = confirmCopy[change.kind].anchor;
    preview.setActionError(null);
    setConfirmation(change);
  }

  async function save(command: SettingsCommand) {
    const saved = await preview.run(command);
    if (command.kind === "set-profile" || command.kind === "set-notifications") {
      setFocusAfterSave({ kind: command.kind });
    }
    if (saved) {
      setConfirmation(null);
      notify(settingsActions[command.kind]);
    }
  }

  function submitConfirmation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmation) return;
    const code = String(new FormData(event.currentTarget).get("confirm") ?? "");
    void save({ ...confirmation, confirmationCode: code });
  }

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Settings" description="Manage preview preferences, sample security controls, and the browser theme." actions={
      <div className="flex flex-wrap items-center gap-2"><Status tone="accent" dot>Demo settings</Status>
        <WorkspacePreviewSelect label="Settings preview data" scenario={preview.scenario} disabled={preview.busy} onChange={preview.load} />
      </div>
    } />
    {!result && <DashboardSkeleton label="Loading settings" />}
    {result?.status === "empty" && <DataState title="No settings to display" description="This sample response has no workspace preferences."
      action={<Button variant="outline" onClick={() => preview.load("ready")}>Load sample settings</Button>} />}
    {result?.status === "denied" && <DataState title="Settings access denied" description="This simulated session cannot read workspace preferences." icon={LockKeyhole}
      action={<Button variant="outline" onClick={() => preview.load("ready")}>Restore demo access</Button>} />}
    {result?.status === "error" && <DataState error title="Settings could not load" description="The demo settings request failed."
      action={<Button variant="outline" onClick={() => preview.load("ready")}>Retry settings</Button>} />}
    {snapshot && <>
      <p className="flex flex-wrap justify-between gap-1.5 border-t border-border pt-3 text-xs text-muted-foreground">
        <span>Sample changes reset when the workspace reloads. Theme is saved in this browser.</span>
        <time dateTime={snapshot.asOf}>Demo snapshot · {formatWorkspaceTime(snapshot.asOf, snapshot.timezone)}</time>
      </p>
      {result?.status === "stale" && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3 text-sm">
        <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Settings are stale. Demo account changes are paused.</p>
        <Button variant="outline" size="sm" onClick={() => preview.load("ready")}>Load latest settings</Button>
      </div>}
      {preview.actionError && !confirmation && <p role="alert" className="text-sm text-negative">{preview.actionError}</p>}
      <div className="grid items-start gap-4 min-[760px]:grid-cols-2">
        <div className="min-w-0 space-y-4">
          <ProfilePreferences key={`${snapshot.displayName}:${snapshot.timezone}`} snapshot={snapshot} disabled={disabled} displayNameRef={displayNameInput} onSave={(command) => void save(command)} />
          <NotificationSettings
            values={snapshot.notifications}
            disabled={disabled}
            saveButtonRef={notificationSaveButton}
            onSave={(command) => void save(command)}
          />
          <BrokerSettingsLink />
        </div>
        <div className="min-w-0 space-y-4">
          <SecuritySettings snapshot={snapshot} disabled={disabled} onConfirm={open} />
          <RiskSettings snapshot={snapshot} disabled={disabled} onConfirm={open} />
          <RetentionSettings snapshot={snapshot} disabled={disabled} onConfirm={open} />
        </div>
      </div>
      <SettingsAudit snapshot={snapshot} />
    </>}

    <Dialog open={confirmation !== null} onOpenChange={(open) => {
      if (!open && !preview.busy) { setConfirmation(null); preview.setActionError(null); }
    }}>
      {confirmation && <DialogContent onCloseAutoFocus={(event) => {
        event.preventDefault();
        const opener = returnFocus.current;
        if (opener?.isConnected && !opener.matches(":disabled")) opener.focus();
        else if (fallback.current) document.getElementById(fallback.current)?.focus();
      }}>
        <DialogTitle>{confirmCopy[confirmation.kind].title}</DialogTitle>
        <DialogDescription>Enter the demo verification code to confirm this change. The preview sends no SMS.</DialogDescription>
        {confirmation.kind === "set-risk" && <p className="mt-3 text-sm">{describeRisk(confirmation.risk)}</p>}
        {confirmation.kind === "set-retention" && <p className="mt-3 text-sm">Save {confirmation.days} days as the demo retention preference.</p>}
        <form className="mt-4 space-y-3" onSubmit={submitConfirmation}>
          <Label htmlFor="settings-code">Demo verification code</Label>
          <Input id="settings-code" name="confirm" inputMode="numeric" autoComplete="off" pattern="[0-9]{6}" maxLength={6} required disabled={preview.busy} aria-describedby="settings-code-hint" />
          <p id="settings-code-hint" className="text-xs text-muted-foreground">Sample code <strong className="text-foreground">{sampleSettingsCode}</strong></p>
          {preview.actionError && <p role="alert" className="text-sm text-negative">{preview.actionError}</p>}
          <Button type="submit" className="h-11" disabled={preview.busy}>{preview.busy ? "Confirming…" : "Confirm demo change"}</Button>
        </form>
      </DialogContent>}
    </Dialog>
  </div>;
}
