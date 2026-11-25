"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { AuthError, authRetryMessage, recoveryCodePattern, requestSignInChallenge, verifySignInChallenge, type EmailChallenge } from "@/lib/auth/browser-client";
import { normalizeEmail } from "@/lib/preview-auth/validation";

type Operation = "request" | "verify";

function errorMessage(error: unknown) {
  if (error instanceof AuthError) {
    if (error.status === 429) return authRetryMessage(error);
    if (error.code === "INVALID_OTP") return "That code didn’t work. Check it and try again, or start over.";
    if (error.code === "OTP_DELIVERY_UNAVAILABLE") return "Sign-in is unavailable because codes can’t be sent right now. Try again later.";
    if (error.status === 403 || error.code === "AUTH_CONTEXT_CHANGED") return "Reload the page and try again.";
  }
  return "Sign-in is temporarily unavailable. Try again shortly.";
}

export function StagingLoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [challenge, setChallenge] = useState<EmailChallenge | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAt, setRetryAt] = useState<Record<Operation, number>>({ request: 0, verify: 0 });
  const proofField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (challenge) proofField.current?.focus();
  }, [challenge, recovery]);

  function resetProof() {
    setCode("");
    setError(null);
  }

  async function submit(operation: Operation) {
    if (pending) return;
    const delay = Math.ceil((retryAt[operation] - Date.now()) / 1000);
    const resendDelay = operation === "request" && challenge ?
      Math.ceil((Date.parse(challenge.resendAvailableAt) - Date.now()) / 1000) : 0;
    if (delay > 0 || resendDelay > 0) {
      setError(`Try again in ${Math.max(delay, resendDelay)} seconds.`);
      return;
    }

    const address = normalizeEmail(email);
    if (!address) {
      setError("Enter a valid email address.");
      return;
    }

    setPending(true);
    setError(null);
    try {
      if (operation === "request") {
        setChallenge(await requestSignInChallenge(address));
        setEmail(address);
        setCode("");
      } else if (challenge) {
        if (Date.parse(challenge.expiresAt) <= Date.now()) {
          setError("This sign-in attempt has expired. Start a new one.");
          return;
        }
        const value = recovery ? code.trim() : code.replace(/\s/g, "");
        if (!(recovery ? recoveryCodePattern : /^\d{6}$/).test(value)) {
          setError(recovery ? "Enter a valid recovery code." : "Enter the six-digit code.");
          return;
        }
        const enrolled = await verifySignInChallenge(challenge.challengeId, recovery ? { recoveryCode: value } : { code: value });
        setCode("");
        router.replace(enrolled ? "/dashboard" : "/login/authenticator");
      }
    } catch (error) {
      if (error instanceof AuthError && error.status === 429 && error.retryAfter) {
        const deadline = Date.now() + error.retryAfter * 1000;
        setRetryAt((previous) => ({ ...previous, [operation]: deadline }));
      }
      setError(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(challenge ? "verify" : "request");
  }

  return <>
    <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
      {challenge ? "Use your authenticator app, or the email code if this is your first sign-in." : "Enter the email address on your Tradeo invite."}
    </p>
    <form className="mt-5 space-y-4" onSubmit={onSubmit}>
      {challenge ? <>
        <p className="break-all text-sm text-muted-foreground">Signing in as {email}.</p>
        <div className="space-y-2">
          <Label htmlFor="staging-code">{recovery ? "Recovery code" : "Six-digit code"}</Label>
          <Input key={String(recovery)} id="staging-code" ref={proofField} value={code} onChange={({ target }) => setCode(target.value)}
            inputMode={recovery ? "text" : "numeric"} autoComplete={recovery ? "off" : "one-time-code"} autoCapitalize="none"
            spellCheck={false} maxLength={recovery ? 11 : 12} readOnly={pending} aria-describedby={error ? "sign-in-error" : undefined} required />
        </div>
      </> : <div className="space-y-2">
        <Label htmlFor="staging-email">Email address</Label>
        <Input id="staging-email" type="email" autoComplete="email" value={email} onChange={({ target }) => setEmail(target.value)}
          maxLength={254} readOnly={pending} aria-describedby={error ? "sign-in-error" : undefined} required />
      </div>}
      {error && <p id="sign-in-error" role="alert" className="text-sm text-negative">{error}</p>}
      <Button type="submit" disabled={pending} className="h-11 w-full font-semibold">
        {pending ? "Please wait…" : challenge ? "Sign in" : "Continue"}
      </Button>
      {challenge && <div className="flex flex-wrap justify-center gap-1">
        <Button type="button" variant="ghost" disabled={pending} onClick={() => { resetProof(); setRecovery(!recovery); }}>
          {recovery ? "Use a six-digit code" : "Use a recovery code"}
        </Button>
        <Button type="button" variant="ghost" disabled={pending} onClick={() => void submit("request")}>Start a new sign-in</Button>
        <Button type="button" variant="ghost" disabled={pending} onClick={() => { resetProof(); setRecovery(false); setChallenge(null); }}>Use a different email</Button>
      </div>}
    </form>
  </>;
}
