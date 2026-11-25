"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { RecoveryCodeList } from "@/components/recovery-code-list";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import type { AccountSession } from "@/lib/api/account-settings-types";
import { AuthError, authRetryMessage, generateRecoveryCodes, verifyAccountStepUp } from "@/lib/auth/browser-client";

export type SecurityAction = { type: "recovery" } | { type: "session"; session: AccountSession };

export function AccountSecurityDialog({ action, onRevoke, onClose, restoreFocus }: {
  action: SecurityAction;
  onRevoke: (session: AccountSession) => Promise<void>;
  onClose: () => void;
  restoreFocus: () => void;
}) {
  const [stepUp, setStepUp] = useState(false);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAt, setRetryAt] = useState(0);
  const codeInput = useRef<HTMLInputElement>(null);
  const codesHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => { if (stepUp) codeInput.current?.focus(); }, [stepUp]);
  useEffect(() => { if (codes) codesHeading.current?.focus(); }, [codes]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const delay = Math.ceil((retryAt - Date.now()) / 1000);
    if (delay > 0) {
      setError(`Try again in ${delay} seconds.`);
      return;
    }
    const proof = code.trim();
    if (stepUp && !/^\d{6}$/.test(proof)) {
      setError("Enter the six-digit code from your authenticator app.");
      return;
    }

    setPending(true);
    setError(null);
    try {
      if (stepUp) {
        await verifyAccountStepUp(proof);
        setStepUp(false);
        setCode("");
      }
      if (action.type === "session") {
        await onRevoke(action.session);
        onClose();
      } else {
        setCodes(await generateRecoveryCodes());
      }
    } catch (error) {
      if (error instanceof AuthError && error.code === "STEP_UP_REQUIRED") {
        setCode("");
        setStepUp(true);
      } else if (error instanceof AuthError && error.code === "INVALID_TOTP") {
        setCode("");
        setError("That code didn’t match. Enter a current code from your authenticator app.");
      } else if (error instanceof AuthError && error.status === 429) {
        if (error.retryAfter) setRetryAt(Date.now() + error.retryAfter * 1000);
        setError(authRetryMessage(error));
      } else if (error instanceof AuthError && (error.status === 401 || error.code === "TOTP_SETUP_REQUIRED")) {
        setError("Sign in again before changing account security.");
      } else {
        setError(action.type === "session" ? "Couldn’t end this session. Try again." : "Couldn’t create recovery codes. Try again.");
      }
    } finally {
      setPending(false);
    }
  }

  const title = codes ? "Save your recovery codes" : stepUp ? "Verify with your authenticator" :
    action.type === "session" ? "End another session?" : "Replace recovery codes?";
  const description = codes ? "Save this list somewhere private. It’s shown only once." : stepUp ?
    "Enter the current code from your authenticator app to confirm this change." : action.type === "session" ?
      `This signs out ${action.session.deviceLabel ?? "the selected device"}.` : "A new set replaces every previously issued recovery code.";

  return <Dialog open onOpenChange={(open) => { if (!open && !pending && (!codes || saved)) onClose(); }}>
    <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus(); }}>
      <DialogTitle ref={codesHeading} tabIndex={-1}>{title}</DialogTitle>
      <DialogDescription>{description}</DialogDescription>
      {codes ? <div className="mt-4 space-y-3">
        <RecoveryCodeList codes={codes} saved={saved} onSaved={setSaved} />
        <Button type="button" disabled={!saved} onClick={onClose}>Done</Button>
      </div> : <form className="mt-4 space-y-3" onSubmit={(event) => void submit(event)}>
        {stepUp && <div className="space-y-1.5">
          <Label htmlFor="account-step-up">Authenticator code</Label>
          <Input id="account-step-up" ref={codeInput} inputMode="numeric" autoComplete="one-time-code" maxLength={6}
            required readOnly={pending} value={code} onChange={({ target }) => setCode(target.value)} />
        </div>}
        {error && <p role="alert" className="text-sm text-negative">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={pending}>{pending ? "Working…" : stepUp ? "Verify and continue" : action.type === "session" ? "End session" : "Create new codes"}</Button>
          <Button type="button" variant="ghost" disabled={pending} onClick={onClose}>Cancel</Button>
        </div>
      </form>}
    </DialogContent>
  </Dialog>;
}
