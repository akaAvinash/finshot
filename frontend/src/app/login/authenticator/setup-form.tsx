"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { QRCodeCanvas } from "qrcode.react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { AuthError, authRetryMessage, confirmAuthenticator, enrollAuthenticator, stagingSignOut, type AuthenticatorEnrollment } from "@/lib/auth/browser-client";

export function AuthenticatorSetup() {
  const router = useRouter();
  const [setup, setSetup] = useState<AuthenticatorEnrollment | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [recoverySaved, setRecoverySaved] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [recentSignInNeeded, setRecentSignInNeeded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAt, setRetryAt] = useState(0);
  const codeField = useRef<HTMLInputElement>(null);
  const recoveryHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (setup) codeField.current?.focus({ preventScroll: true });
  }, [setup]);

  useEffect(() => {
    if (recoveryCodes) recoveryHeading.current?.focus();
  }, [recoveryCodes]);

  function clearSetup() {
    setSetup(null);
    setShowKey(false);
    setCode("");
  }

  function handleError(error: unknown) {
    if (error instanceof AuthError) {
      if (error.status === 401 || error.code === "STEP_UP_REQUIRED") {
        clearSetup();
        setRecentSignInNeeded(true);
        setError("Sign out and verify your email again to start a fresh setup.");
        return;
      }
      if (error.code === "TOTP_ALREADY_ENROLLED") {
        clearSetup();
        router.refresh();
        return;
      }
      if (error.code === "TOTP_NOT_PENDING") {
        clearSetup();
        setError("This setup key has expired. Start setup again.");
        return;
      }
      if (error.code === "INVALID_TOTP") {
        setError("The code is invalid or expired. Enter the current code from your authenticator app.");
        return;
      }
      if (error.status === 429) {
        if (error.retryAfter) setRetryAt(Date.now() + error.retryAfter * 1000);
        setError(authRetryMessage(error));
        return;
      }
    }
    setError("Authenticator setup is temporarily unavailable. Try again shortly.");
  }

  async function perform(confirm: boolean) {
    if (pending || leaving || recentSignInNeeded) return;
    const delay = Math.ceil((retryAt - Date.now()) / 1000);
    if (delay > 0) {
      setError(`Try again in ${delay} seconds.`);
      return;
    }

    const digits = code.trim();
    if (confirm) {
      if (!setup || Date.parse(setup.expiresAt) <= Date.now()) {
        clearSetup();
        setError("This setup key has expired. Start setup again.");
        return;
      }
      if (!/^\d{6}$/.test(digits)) {
        setError("Enter the six-digit code.");
        return;
      }
    }

    setPending(true);
    setError(null);
    try {
      if (confirm) {
        const codes = await confirmAuthenticator(digits);
        clearSetup();
        setRecoveryCodes(codes);
      } else {
        const enrollment = await enrollAuthenticator();
        setSetup(enrollment);
        setShowKey(false);
        setCode("");
      }
    } catch (error) {
      handleError(error);
    } finally {
      setPending(false);
    }
  }

  async function signOut() {
    if (pending || leaving) return;
    setLeaving(true);
    setError(null);
    const message = await stagingSignOut();
    if (message) {
      setLeaving(false);
      setError(message);
    } else clearSetup();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void perform(true);
  }

  if (recoveryCodes) return <section className="mt-5 space-y-4" aria-labelledby="recovery-heading">
    <h2 id="recovery-heading" ref={recoveryHeading} tabIndex={-1} className="text-lg font-semibold">Save your recovery codes</h2>
    <p className="text-sm text-muted-foreground">Keep these in a private place. Each code can be used once if you lose access to your authenticator. These codes are shown only now.</p>
    <ul aria-label="Recovery codes" className="grid grid-cols-2 gap-2 rounded-md border border-border bg-background p-3 text-center font-mono text-sm">
      {recoveryCodes.map((recoveryCode) => <li className="select-all" key={recoveryCode}>{recoveryCode}</li>)}
    </ul>
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary" checked={recoverySaved}
        onChange={({ target }) => setRecoverySaved(target.checked)} />
      I’ve saved my recovery codes.
    </label>
    <Button type="button" disabled={!recoverySaved || leaving} className="h-11 w-full" onClick={() => {
      setLeaving(true);
      router.replace("/dashboard");
    }}>Continue to dashboard</Button>
  </section>;

  return <div className="mt-5 space-y-4">
    {setup && <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Scan the QR code in your authenticator app, or use the setup key.</p>
      <div className="flex justify-center">
        <QRCodeCanvas value={setup.otpauthUri} size={192} marginSize={4} level="M" role="img" aria-label="Tradeo authenticator setup QR code" className="rounded-md" />
      </div>
      <Button type="button" variant="outline" size="sm" aria-expanded={showKey} aria-controls="manual-setup-key"
        onClick={() => setShowKey((visible) => !visible)}>{showKey ? "Hide setup key" : "Show setup key"}</Button>
      <div id="manual-setup-key" hidden={!showKey} className="rounded-md border border-border bg-background p-3">
        {showKey && <code className="wrap-anywhere select-all text-sm">{setup.secret}</code>}
      </div>
    </div>}
    {error && <p id="setup-error" role="alert" className="text-sm text-negative">{error}</p>}
    {setup ? <form onSubmit={submit} className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor="setup-code">Authenticator code</Label>
        <Input id="setup-code" ref={codeField} inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000"
          value={code} onChange={({ target }) => setCode(target.value)} readOnly={pending || leaving}
          aria-describedby={error ? "setup-error" : undefined} required />
      </div>
      <Button type="submit" aria-disabled={pending || leaving} className="h-11 w-full aria-disabled:opacity-50">Confirm authenticator</Button>
      <Button type="button" variant="ghost" aria-disabled={pending || leaving} onClick={() => void perform(false)} className="w-full">Generate a new setup key</Button>
    </form> : !recentSignInNeeded && !leaving && <Button type="button" aria-disabled={pending}
      className="h-11 w-full aria-disabled:opacity-50" onClick={() => void perform(false)}>{pending ? "Starting setup…" : "Start authenticator setup"}</Button>}
    <Button type="button" variant="ghost" aria-disabled={pending || leaving} className="w-full" onClick={() => void signOut()}>Sign out</Button>
  </div>;
}
