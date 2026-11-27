"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { PageHeading } from "@/components/page-heading";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { brokerCallbackPath, completeBrokerAuthorization, parseBrokerCallback, type BrokerCallback } from "@/lib/api/broker-connections-client";
import { stagingError } from "@/lib/api/staging-client";
import { AuthError } from "@/lib/auth/browser-client";

export function BrokerCallbackPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [terminal, setTerminal] = useState(false);
  const [retryUntil, setRetryUntil] = useState(0);
  const pendingCallback = useRef<BrokerCallback | null | undefined>(undefined);
  const controller = useRef<AbortController | null>(null);
  const router = useRouter();
  const notify = useNotification();
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!retryUntil) return;
    const timer = setTimeout(() => setRetryUntil(0), Math.max(0, retryUntil - Date.now()));
    return () => clearTimeout(timer);
  }, [retryUntil]);

  async function complete() {
    if (controller.current || terminal || retryUntil) return;
    if (pendingCallback.current === undefined) {
      pendingCallback.current = parseBrokerCallback(new URLSearchParams(window.location.search)) ?? null;
      window.history.replaceState(window.history.state, "", brokerCallbackPath);
    }
    const payload = pendingCallback.current;
    if (!payload) {
      setTerminal(true);
      setError("The demo authorization was incomplete. Return to Brokers and start again.");
      return;
    }
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setError("");
    try {
      await completeBrokerAuthorization(payload, request.signal);
      if (!request.signal.aborted) {
        pendingCallback.current = null;
        setTerminal(true);
        notify("Demo broker authorization completed.");
        router.replace("/brokers");
      }
    } catch (error) {
      if (request.signal.aborted) return;
      if (error instanceof AuthError && error.status === 429) {
        if (error.retryAfter) setRetryUntil(Date.now() + error.retryAfter * 1000);
        setError(stagingError(error, "Authorization is rate limited. Try again shortly."));
      } else {
        pendingCallback.current = null;
        setTerminal(true);
        setError(stagingError(error, "The authorization could not be confirmed. Return to Brokers to check the connection."));
      }
    } finally {
      controller.current = null;
      if (!request.signal.aborted) setBusy(false);
    }
  }
  return <div className="space-y-4">
    <PageHeading title="Complete broker authorization" description="Confirm read-only access for this demo broker connection." actions={<Status tone="accent">Demo only</Status>} />
    <Card className="space-y-4 p-4 sm:p-5">
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={busy || terminal || !!retryUntil} onClick={() => void complete()}>
          {busy ? "Confirming…" : error && !terminal ? "Retry demo authorization" : "Complete demo authorization"}
        </Button>
        <Button asChild variant="outline"><Link href="/brokers">Return to Brokers</Link></Button>
      </div>
    </Card>
  </div>;
}
