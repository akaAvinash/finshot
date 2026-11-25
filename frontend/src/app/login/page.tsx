import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { FlaskConical, ShieldCheck } from "lucide-react";
import { Wordmark } from "@/components/wordmark";
import { ThemeToggle } from "@/components/theme-toggle";
import { Status } from "@/components/ui/status";
import { getWorkspaceSession } from "@/lib/auth/workspace-session";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign-in" };

export default async function LoginPage() {
  const { mode, signedIn } = await getWorkspaceSession();
  if (signedIn) redirect("/dashboard");
  const preview = mode === "preview";

  return (
    <main className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-sidebar p-12 lg:flex xl:p-16">
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,var(--chart-fill),transparent_60%)]" />
        <div className="relative"><Wordmark /></div>
        <div className="relative max-w-lg">
          <Status tone="accent"><FlaskConical aria-hidden className="size-3.5" /> {preview ? "Frontend preview" : "Private staging"}</Status>
          <p className="mt-6 text-[clamp(2.75rem,5.3vw,5.1rem)] leading-[0.99] font-semibold tracking-[-0.07em]">
            Your Indian<br className="hidden xl:block" /> trading workspace<span className="text-accent-foreground">.</span>
          </p>
          <p className="mt-6 max-w-sm leading-relaxed text-muted-foreground">
            Explore portfolio performance, a market watchlist and sample activity in one dashboard.
          </p>
        </div>
        <p className="relative text-sm text-muted-foreground">Tradeo {preview ? "preview" : "staging"} · India</p>
      </aside>
      <div className="relative flex min-h-dvh flex-col">
        <header className="flex h-18 items-center justify-between px-6 sm:px-10 lg:justify-end">
          <div className="lg:hidden"><Wordmark /></div>
          <ThemeToggle />
        </header>
        <div className="flex flex-1 items-center justify-center px-5 pb-18 sm:px-10">
          <section aria-labelledby="login-heading" className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-sm sm:p-9">
            <div className="mb-5 inline-flex size-11 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-accent-foreground">
              <ShieldCheck aria-hidden className="size-5" />
            </div>
            <h1 id="login-heading" className="text-3xl font-semibold tracking-[-0.055em]">{preview ? "Preview sign-in" : "Staging sign-in"}</h1>
            {mode === "unavailable" ? (
              <p role="alert" className="mt-2 text-sm leading-relaxed text-negative">Sign-in is temporarily unavailable. Reload to try again.</p>
            ) : (
              <>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {preview ? "Use any sample Indian mobile number to open the simulated workspace. No SMS will be sent." : "Use an authorized staging mobile number to request a one-time code."}
                </p>
                <LoginForm mode={mode} />
              </>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
