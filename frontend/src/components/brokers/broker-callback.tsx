"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { PageHeading } from "@/components/page-heading";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import { brokerCallbackPath, completeBrokerAuthorization, parseBrokerCallback } from "@/lib/api/broker-connections-client";
import { stagingError } from "@/lib/api/staging-client";

export function BrokerCallbackPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const router = useRouter();
  const notify = useNotification();
  useEffect(() => () => controller.current?.abort(), []);

  async function complete() {
    if (controller.current) return;
    const payload = parseBrokerCallback(new URLSearchParams(window.location.search));
    window.history.replaceState(window.history.state, "", brokerCallbackPath);
    if (!payload) { setError("The demo authorization was incomplete. Return to Brokers and start again."); return; }
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    try {
      await completeBrokerAuthorization(payload, request.signal);
      if (!request.signal.aborted) {
        notify("Demo broker authorization completed.");
        router.replace("/brokers");
      }
    } catch (error) {
      if (!request.signal.aborted) setError(stagingError(error, "The authorization could not be confirmed. Return to Brokers to check the connection."));
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
        <Button type="button" disabled={busy || !!error} onClick={() => void complete()}>{busy ? "Confirming…" : "Complete demo authorization"}</Button>
        <Button asChild variant="outline"><Link href="/brokers">Return to Brokers</Link></Button>
      </div>
    </Card>
  </div>;
}
