"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Bell, KeyRound, Monitor, UserRound } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { endAccountSession, getAccountProfile, listAccountSessions, saveAccountProfile } from "@/lib/api/account-settings-client";
import { accountTimezones, type AccountProfile, type AccountSession } from "@/lib/api/account-settings-types";
import { AuthError } from "@/lib/auth/browser-client";
import { formatWorkspaceTime, timezoneLabels } from "@/lib/workspace-controls";
import { AppearancePreferences, SettingsCard } from "./settings-preferences";
import { AccountSecurityDialog, type SecurityAction } from "./account-security-dialog";

type Resource<T> = { state: "loading" } | { state: "error"; error: unknown } | { state: "ready"; data: T };

function useAccountResource<T>(read: (signal: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<Resource<T>>({ state: "loading" });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void read(controller.signal).then((data) => {
      if (!controller.signal.aborted) setResult({ state: "ready", data });
    }, (error: unknown) => {
      if (!controller.signal.aborted) setResult({ state: "error", error });
    });
    return () => controller.abort();
  }, [read, revision]);

  return { result, setResult, retry: () => {
    setResult({ state: "loading" });
    setRevision((value) => value + 1);
  } };
}

function ReadError({ error, name, retry }: { error: unknown; name: string; retry: () => void }) {
  const needsSignIn = error instanceof AuthError && (error.status === 401 || error.code === "TOTP_SETUP_REQUIRED");
  return <div className="space-y-2">
    <p role="alert" className="text-sm text-negative">{needsSignIn ? "Sign in again to continue." : `Couldn’t load ${name}.`}</p>
    {needsSignIn ? <Button asChild variant="outline"><Link href="/login">Go to sign-in</Link></Button> :
      <Button variant="outline" onClick={retry}>Retry {name}</Button>}
  </div>;
}

function ProfileForm({ profile, onSave }: { profile: AccountProfile; onSave: (profile: AccountProfile) => void }) {
  const [name, setName] = useState(profile.displayName ?? "");
  const [timeZone, setTimeZone] = useState(profile.timezone);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notify = useNotification();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const data = new FormData(event.currentTarget);
    const displayName = String(data.get("displayName") ?? "").trim();
    const timezone = accountTimezones.find((value) => value === data.get("timezone"));
    if (!timezone || !displayName || Array.from(displayName).length > 48 || /\p{Cc}/u.test(displayName)) {
      setError("Enter a display name between 1 and 48 characters and select a timezone.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await saveAccountProfile({ displayName, timezone });
      setName(saved.displayName ?? "");
      setTimeZone(saved.timezone);
      onSave(saved);
      notify("Profile saved.");
    } catch (error) {
      setError(error instanceof AuthError && error.status === 401 ? "Your session expired. Sign in and try again." : "Couldn’t save your profile. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return <form onSubmit={(event) => void submit(event)}>
    <fieldset disabled={saving} className="space-y-3">
      <p className="text-sm text-muted-foreground">Account phone <span className="ml-1 font-medium text-foreground">{profile.phoneMasked}</span></p>
      <div className="space-y-1.5"><Label htmlFor="account-display-name">Display name</Label>
        <Input id="account-display-name" name="displayName" value={name} onChange={(event) => setName(event.target.value)} autoComplete="nickname" maxLength={96} required />
      </div>
      <div className="space-y-1.5"><Label htmlFor="account-timezone">Timezone</Label>
        <select id="account-timezone" name="timezone" value={timeZone} onChange={(event) => {
          const timezone = accountTimezones.find((value) => value === event.target.value);
          if (timezone) setTimeZone(timezone);
        }} className="h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-base sm:text-sm">
          {accountTimezones.map((value) => <option key={value} value={value}>{timezoneLabels[value]}</option>)}
        </select>
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      <Button type="submit" variant="outline" className="h-11">{saving ? "Saving…" : "Save profile"}</Button>
    </fieldset>
  </form>;
}

export function AccountSettings() {
  const profile = useAccountResource(getAccountProfile);
  const sessions = useAccountResource(listAccountSessions);
  const [action, setAction] = useState<SecurityAction | null>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const notify = useNotification();
  const timezone = profile.result.state === "ready" ? profile.result.data.timezone : "Asia/Kolkata";

  function open(next: SecurityAction, button: HTMLButtonElement) {
    opener.current = button;
    setAction(next);
  }

  async function revoke(session: AccountSession) {
    try {
      await endAccountSession(session.id);
      notify("Session ended.");
    } catch (error) {
      if (!(error instanceof AuthError) || error.status !== 404) throw error;
      notify("This session has already ended.");
    }
    if (sessions.result.state === "ready") {
      sessions.setResult({ state: "ready", data: sessions.result.data.filter(({ id }) => id !== session.id) });
    }
  }

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Settings" description="Manage your account profile, active sessions, recovery codes, and alerts." />
    <div className="grid items-start gap-4 min-[760px]:grid-cols-2">
      <div className="min-w-0 space-y-4">
        <SettingsCard id="profile-preferences" title="Profile and appearance" description="Your profile is saved to your account. Theme is saved in this browser." icon={UserRound}>
          {profile.result.state === "loading" && <p role="status" className="text-sm text-muted-foreground">Loading profile…</p>}
          {profile.result.state === "error" && <ReadError name="profile" error={profile.result.error} retry={profile.retry} />}
          {profile.result.state === "ready" && <ProfileForm profile={profile.result.data}
            onSave={(data) => profile.setResult({ state: "ready", data })} />}
          <AppearancePreferences />
        </SettingsCard>
        <SettingsCard id="notification-preferences" title="Notifications" description="Choose which optional in-app alerts appear for your account." icon={Bell}>
          <Button asChild variant="outline"><Link href="/alerts#account-alert-preferences">Manage alert preferences</Link></Button>
        </SettingsCard>
        <SettingsCard id="staging-settings-availability" title="Paper risk limits" description="Review the paper engine’s limits and recent changes." icon={Monitor}>
          <Button asChild variant="outline"><Link href="/auto-trading#paper-trade-controls">Manage paper limits</Link></Button>
        </SettingsCard>
      </div>
      <div className="min-w-0 space-y-4">
        <SettingsCard id="account-sessions" title="Active sessions" description="Review signed-in devices and end sessions you no longer use." icon={Monitor}>
          {sessions.result.state === "loading" && <p role="status" className="text-sm text-muted-foreground">Loading sessions…</p>}
          {sessions.result.state === "error" && <ReadError name="sessions" error={sessions.result.error} retry={sessions.retry} />}
          {sessions.result.state === "ready" && (sessions.result.data.length === 0 ? <p className="text-sm text-muted-foreground">No active sessions to display.</p> :
            <ul aria-label="Active sessions" className="space-y-2">
              {sessions.result.data.map((session) => <li key={session.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-background/45 p-3">
                <div className="min-w-0">
                  <p className="wrap-anywhere text-sm font-medium">{session.deviceLabel ?? "Unknown device"}</p>
                  <p className="mt-1 text-xs text-muted-foreground">Last active <time dateTime={session.lastSeenAt}>{formatWorkspaceTime(session.lastSeenAt, timezone)}</time></p>
                </div>
                {session.current ? <Status tone="accent">Current session</Status> : <Button type="button" size="sm" variant="outline"
                  aria-label={`End session for ${session.deviceLabel ?? "unknown device"}`}
                  onClick={(event) => open({ type: "session", session }, event.currentTarget)}>End session</Button>}
              </li>)}
            </ul>)}
        </SettingsCard>
        <SettingsCard id="account-recovery" title="Recovery codes" description="Create a new set if your previous codes are missing or may be exposed." icon={KeyRound}>
          <Button type="button" variant="outline" onClick={(event) => open({ type: "recovery" }, event.currentTarget)}>Generate recovery codes</Button>
        </SettingsCard>
      </div>
    </div>
    {action && <AccountSecurityDialog action={action} onRevoke={revoke} onClose={() => setAction(null)} restoreFocus={() => {
      if (opener.current?.isConnected) opener.current.focus();
      else document.getElementById(action.type === "session" ? "account-sessions" : "account-recovery")?.focus();
    }} />}
  </div>;
}
