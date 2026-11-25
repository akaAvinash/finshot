"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { previewLogin, type LoginState } from "./actions";

const initialState: LoginState = { step: "phone" };

export function LoginForm() {
  const [state, action, pending] = useActionState(previewLogin, initialState);
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
          <p className="text-sm text-muted-foreground">Preview number ending in {state.phone.slice(-4)}.</p>
          <Label htmlFor="code">One-time code</Label>
          <Input
            id="code"
            name="code"
            ref={codeField}
            inputMode="numeric"
            autoComplete="off"
            maxLength={6}
            placeholder="000000"
            aria-describedby={state.error ? "demo-code login-error" : "demo-code"}
            aria-invalid={!!state.error}
            required
          />
          <p id="demo-code" className="rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm">
            Use preview code <strong className="text-accent-foreground">123456</strong>.
          </p>
        </div>
      )}
      {state.error && <p id="login-error" role="alert" className="text-sm text-negative">{state.error}</p>}
      <Button type="submit" className="h-11 w-full font-semibold" disabled={pending}>
        {pending ? "Please wait…" : state.step === "phone" ? "Get preview code" : "Open dashboard"}
      </Button>
      {state.step === "code" && (
        <Button variant="ghost" type="submit" name="intent" value="change-phone" formNoValidate disabled={pending} className="w-full">
          Change mobile number
        </Button>
      )}
    </form>
  );
}
