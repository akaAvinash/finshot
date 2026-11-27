"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { AuthError, authRetryMessage, recoveryCodePattern, requestEmailCode, signInWithAuthenticator, signInWithRecoveryCode, signInWithTesterInvite, testerInviteCodePattern, verifyEmailCode, type EmailChallenge } from "@/lib/auth/browser-client";
import { normalizeIndianMobile } from "@/lib/preview-auth/validation";
import { cn } from "@/lib/utils";

const methods = { authenticator: "Authenticator", email: "First-time email", recovery: "Recovery code", tester: "Tester invite" } as const;
type Method = keyof typeof methods;
type RetryGroup = "authenticator" | "email" | "tester";
type EmailVerification = EmailChallenge & { phone: string };

function errorMessage(error: unknown, method: Method) {
  if (error instanceof AuthError) {
    if (method === "tester" && error.status === 404) return "Tester sign-in is currently unavailable.";
    if (error.status === 429) return authRetryMessage(error);
    if (error.code === "INVALID_CREDENTIALS") return "The phone number or code is not valid.";
    if (error.code === "INVALID_OTP") return "This code is invalid, expired, or used. Try again or request a new code.";
    if (error.code === "OTP_DELIVERY_UNAVAILABLE") return "Email code delivery is unavailable. Try again later.";
    if (error.status === 403 || error.code === "AUTH_CONTEXT_CHANGED") return "Reload the page and try again.";
  }
  return "Sign-in is temporarily unavailable. Try again shortly.";
}

export function StagingLoginForm({ testerSignInEnabled = false }: { testerSignInEnabled?: boolean }) {
  const router = useRouter();
  const [method, setMethod] = useState<Method>("authenticator");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<EmailVerification | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAt, setRetryAt] = useState<Record<RetryGroup, number>>({ authenticator: 0, email: 0, tester: 0 });
  const codeField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (challenge) codeField.current?.focus();
  }, [challenge]);

  function resetEmail() {
    if (pending) return;
    setChallenge(null);
    setCode("");
    setError(null);
  }

  function changeMethod(next: Method) {
    if (pending || next === method) return;
    resetEmail();
    setMethod(next);
  }

  async function submit(resend = false) {
    if (pending) return;
    const number = challenge?.phone ?? normalizeIndianMobile(phone);
    if (!number) {
      setError("Enter a valid 10-digit Indian mobile number.");
      return;
    }
    const requesting = method === "email" && (!challenge || resend);
    const retryGroup = method === "recovery" ? "authenticator" : method;
    const delay = Math.ceil((retryAt[retryGroup] - Date.now()) / 1000);
    const resendDelay = resend && challenge ? Math.ceil((Date.parse(challenge.resendAvailableAt) - Date.now()) / 1000) : 0;
    if (delay > 0 || resendDelay > 0) {
      setError(`Try again in ${Math.max(delay, resendDelay)} seconds.`);
      return;
    }
    const recovery = method === "recovery";
    const tester = method === "tester";
    const proof = recovery ? code.trim().toUpperCase() : code.trim();
    const pattern = tester ? testerInviteCodePattern : recovery ? recoveryCodePattern : /^\d{6}$/;
    if (!requesting && !pattern.test(proof)) {
      setError(tester ? "Enter the 22-character invite code." : recovery ? "Enter a recovery code from your saved list." : "Enter the six-digit code.");
      return;
    }
    if (!requesting && challenge && Date.now() >= Date.parse(challenge.expiresAt)) {
      setError("This email code has expired. Request a new code.");
      return;
    }

    setPending(true);
    setError(null);
    try {
      if (requesting) {
        setChallenge({ ...await requestEmailCode(number), phone: number });
        setCode("");
      } else if (tester) {
        await signInWithTesterInvite(number, proof);
        setCode("");
        router.replace("/dashboard");
      } else {
        const enrolled = challenge ? await verifyEmailCode(challenge.challengeId, proof) : recovery ?
          await signInWithRecoveryCode(number, proof) : await signInWithAuthenticator(number, proof);
        setCode("");
        router.replace(enrolled ? "/dashboard" : "/login/authenticator");
      }
    } catch (error) {
      if (error instanceof AuthError && error.status === 429 && error.retryAfter) {
        const deadline = Date.now() + error.retryAfter * 1000;
        setRetryAt((previous) => ({ ...previous, [retryGroup]: deadline }));
      }
      setError(errorMessage(error, method));
    } finally {
      setPending(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  const email = method === "email";
  const recovery = method === "recovery";
  const tester = method === "tester";
  return <>
    <div role="group" aria-label="Sign-in method" className={cn("mt-5 grid gap-1 rounded-lg border border-border bg-background p-1", testerSignInEnabled ? "grid-cols-2" : "grid-cols-3")}>
      {(Object.keys(methods) as Method[]).filter((option) => testerSignInEnabled || option !== "tester").map((option) => <Button key={option} type="button" size="sm"
        variant={option === method ? "default" : "ghost"} aria-pressed={option === method} aria-disabled={pending}
        className="px-1 text-xs" onClick={() => changeMethod(option)}>{methods[option]}</Button>)}
    </div>
    <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
      {tester ? "Enter the mobile number and single-use invite code you received. Tester access is limited to paper and demo trading." :
        email ? "If your number is invited, we’ll send a code to the email on file." : recovery ?
        "Use a saved recovery code to sign in and replace your authenticator. This retires your other recovery codes." :
        "Enter your mobile number and the current code from your authenticator app."}
    </p>
    <form className="mt-5 space-y-4" onSubmit={onSubmit}>
      {!challenge && <div className="space-y-2">
        <Label htmlFor="staging-phone">Mobile number</Label>
        <div className="relative">
          <span aria-hidden className="pointer-events-none absolute inset-y-0 left-3 flex items-center gap-2 text-sm text-muted-foreground"><Smartphone className="size-4" /> +91</span>
          <Input id="staging-phone" type="tel" autoComplete="tel-national" value={phone} onChange={({ target }) => setPhone(target.value)}
            className="pl-19" maxLength={18} placeholder="98765 43210" readOnly={pending} required />
        </div>
      </div>}
      {challenge && <p className="text-sm text-muted-foreground">Code requested for the number ending in {challenge.phone.slice(-4)}.</p>}
      {(!email || challenge) && <div className="space-y-2">
        <Label htmlFor="staging-code">{tester ? "Invite code" : email ? "Email verification code" : recovery ? "Recovery code" : "Authenticator code"}</Label>
        <Input id="staging-code" ref={codeField} type={tester ? "password" : "text"} value={code} onChange={({ target }) => setCode(target.value)} inputMode={recovery || tester ? "text" : "numeric"}
          autoComplete={recovery || tester ? "off" : "one-time-code"} autoCapitalize={recovery ? "characters" : tester ? "none" : undefined} spellCheck={false}
          maxLength={tester ? 22 : recovery ? 11 : 6} placeholder={recovery || tester ? undefined : "000000"} readOnly={pending} required />
      </div>}
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      <Button type="submit" aria-disabled={pending} className="h-11 w-full font-semibold aria-disabled:opacity-50">
        {pending ? "Please wait…" : challenge ? "Verify email code" : email ? "Request code" : "Sign in"}
      </Button>
      {challenge && <div className="flex flex-wrap justify-center gap-1">
        <Button type="button" variant="ghost" aria-disabled={pending} onClick={() => void submit(true)}>Request a new code</Button>
        <Button type="button" variant="ghost" aria-disabled={pending} onClick={resetEmail}>Change mobile number</Button>
      </div>}
    </form>
  </>;
}
