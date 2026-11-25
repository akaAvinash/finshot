"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { stagingLogin, type LoginState } from "@/lib/auth/browser-client";
import type { AuthMode } from "@/lib/auth/config";
import { previewLogin } from "./actions";

const initialState: LoginState = { step: "phone" };

export function LoginForm({ mode }: { mode: AuthMode }) {
  const preview = mode === "preview";
  const [state, action, pending] = useActionState(preview ? previewLogin : stagingLogin, initialState);
  const [phone, setPhone] = useState("");
  const codeField = useRef<HTMLInputElement>(null);
  const step = state.step;

  useEffect(() => {
    if (step === "code") codeField.current?.focus();
  }, [step]);

  return (
    <form action={action} className="mt-7 space-y-5">
      {state.step === "phone" ? (
        <div className="space-y-2">
          <Label htmlFor="phone">Mobile number</Label>
          <div className="relative">
            <span aria-hidden className="pointer-events-none absolute inset-y-0 left-3 flex items-center gap-2 text-sm text-muted-foreground">
              <Smartphone className="size-4" /> +91
            </span>
            <Input
              id="phone"
              name="phone"
              type="tel"
              autoComplete="tel-national"
              inputMode="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="98765 43210"
              className="pl-19"
              aria-invalid={!!state.error}
              aria-describedby={state.error ? "login-error" : undefined}
              required
              maxLength={18}
            />
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">{preview ? "Preview number ending in" : "Code requested for the number ending in"} {state.phone.slice(-4)}.</p>
          <Label htmlFor="code">One-time code</Label>
          <Input
            id="code"
            name="code"
            ref={codeField}
            inputMode="numeric"
            autoComplete={preview ? "off" : "one-time-code"}
            maxLength={6}
            placeholder="000000"
            aria-describedby={[preview && "demo-code", state.error && "login-error"].filter(Boolean).join(" ") || undefined}
            aria-invalid={!!state.error}
            required
          />
          {preview && <p id="demo-code" className="rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm">
            Use preview code <strong className="text-accent-foreground">123456</strong>.
          </p>}
        </div>
      )}
      {state.error && <p id="login-error" role="alert" className="text-sm text-negative">{state.error}</p>}
      <Button type="submit" className="h-11 w-full font-semibold" disabled={pending}>
        {pending ? "Please wait…" : state.step === "phone" ? (preview ? "Get preview code" : "Request code") : (preview ? "Open dashboard" : "Verify and sign in")}
      </Button>
      {!preview && state.step === "code" && (
        <Button variant="outline" type="submit" name="intent" value="resend" formNoValidate disabled={pending} className="w-full">
          Request a new code
        </Button>
      )}
      {state.step === "code" && (
        <Button variant="ghost" type="submit" name="intent" value="change-phone" formNoValidate disabled={pending} className="w-full">
          Change mobile number
        </Button>
      )}
    </form>
  );
}
