"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { AlertRequestError, readAlertPreferences, saveAlertPreferences } from "@/lib/api/alerts-client";
import type { AlertPreferences, InAppPreferences } from "@/lib/api/alerts-types";

const channelLabel = { email: "Email", sms: "SMS", push: "Push" } as const;

export function AccountAlertPreferences({ onSaved }: { onSaved: () => void }) {
  const [version, setVersion] = useState(0);
  const [loaded, setLoaded] = useState<{ version: number; data?: AlertPreferences; error?: number }>();
  const [draft, setDraft] = useState<InAppPreferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<number | null>(null);
  const notify = useNotification();
  const result = loaded?.version === version ? loaded : undefined;
  const snapshot = result?.data;
  const selected = draft ?? snapshot?.inApp;
  const dirty = selected && snapshot && (selected.warning !== snapshot.inApp.warning || selected.info !== snapshot.inApp.info);

  useEffect(() => {
    const controller = new AbortController();
    readAlertPreferences(controller.signal).then((data) => {
      if (!controller.signal.aborted) setLoaded({ version, data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setLoaded({ version, error: error instanceof AlertRequestError ? error.status : 503 });
    });
    return () => controller.abort();
  }, [version]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dirty || !selected || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const data = await saveAlertPreferences({ warning: selected.warning, info: selected.info });
      setLoaded({ version, data });
      setDraft(null);
      onSaved();
      notify("Alert preferences saved");
    } catch (error) {
      setSaveError(error instanceof AlertRequestError ? error.status : 503);
    } finally {
      setSaving(false);
    }
  }

  return <Card aria-labelledby="account-alert-preferences" className="scroll-mt-20 p-4 sm:p-5">
    <h2 id="account-alert-preferences" className="flex items-center gap-2 font-semibold"><Settings2 aria-hidden className="size-4 text-accent-foreground" /> Delivery preferences</h2>
    {!result && <p role="status" className="mt-3 text-sm text-muted-foreground">Loading preferences…</p>}
    {result?.error && <div role="alert" className="mt-3 space-y-3 text-sm text-negative">
      <p>{result.error === 401 ? "Your session has expired." : "Preferences could not load."}</p>
      {result.error === 401 ? <Button asChild variant="outline"><Link href="/login">Sign in again</Link></Button> :
        <Button variant="outline" onClick={() => setVersion((value) => value + 1)}>Retry preferences</Button>}
    </div>}
    {snapshot && selected && <>
      <form onSubmit={(event) => void submit(event)} className="mt-2">
        <div className="flex items-center justify-between gap-2 border-b border-border py-3 text-sm"><span>Critical alerts</span><Status tone="positive">Always on</Status></div>
        <fieldset disabled={saving} className="divide-y divide-border">
          {(["warning", "info"] as const).map((key) => <label key={key} className="flex min-h-11 items-center justify-between gap-2 py-2 text-sm">
            {key === "warning" ? "Warning alerts" : "Info alerts"}
            <input type="checkbox" checked={selected[key]} className="size-4 shrink-0 accent-primary"
              onChange={({ target }) => setDraft({ warning: selected.warning, info: selected.info, [key]: target.checked })} />
          </label>)}
        </fieldset>
        {saveError && <p role="alert" className="mt-2 text-xs text-negative">{saveError === 401 ?
          <Link href="/login" className="underline">Sign in again to save preferences.</Link> : "Preferences could not be saved. Try again."}</p>}
        <Button variant="outline" type="submit" aria-disabled={!dirty || saving} className="mt-2 h-11 w-full aria-disabled:opacity-50">
          {saving ? "Saving…" : "Save alert preferences"}
        </Button>
      </form>
      <dl className="mt-4 divide-y divide-border border-t border-border">
        {snapshot.channels.map(({ channel }) => <div key={channel} className="flex items-center justify-between gap-2 py-2.5 text-sm">
          <dt>{channelLabel[channel]}</dt><dd><Status>Unavailable</Status></dd>
        </div>)}
      </dl>
    </>}
  </Card>;
}
