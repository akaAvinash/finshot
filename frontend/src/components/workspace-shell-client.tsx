"use client";

import { useActionState, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, ChevronRight, FlaskConical, LogOut, Menu } from "lucide-react";
import { signOut } from "@/app/login/actions";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Status } from "@/components/ui/status";
import { Wordmark } from "@/components/wordmark";
import { workspaceRoutes } from "@/lib/navigation";
import { stagingSignOut } from "@/lib/auth/browser-client";
import type { AuthMode } from "@/lib/auth/config";
import { cn } from "@/lib/utils";

function Navigation({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Workspace" className="space-y-1">
      {workspaceRoutes.map(({ slug, title, icon: Icon }) => {
        const href = `/${slug}`;
        const active = pathname === href;

        return (
          <Link
            key={slug}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface-raised hover:text-foreground",
            )}
          >
            <Icon aria-hidden className="size-[1.14rem] shrink-0" strokeWidth={1.8} />
            {title}
          </Link>
        );
      })}
    </nav>
  );
}

function SessionControls({ mode }: { mode: AuthMode }) {
  const preview = mode === "preview";
  const [error, action, pending] = useActionState(preview ? signOut : stagingSignOut, null);
  return (
    <div className="border-t border-border pt-3">
      <div className="mb-2 flex items-center gap-2 px-3 text-xs text-muted-foreground">
        <FlaskConical aria-hidden className="size-3.5 text-accent-foreground" /> {preview ? "Simulated session" : "Staging session"}
      </div>
      <form action={action}>
        <Button type="submit" variant="ghost" className="w-full justify-start px-3" disabled={pending}>
          <LogOut aria-hidden /> {pending ? "Signing out…" : "Sign out"}
        </Button>
      </form>
      {error && <p role="alert" className="px-3 pt-2 text-xs text-negative">{error}</p>}
    </div>
  );
}

export function WorkspaceShellClient({ mode, children }: { mode: AuthMode; children: ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const activeRoute = workspaceRoutes.find(({ slug }) => pathname === `/${slug}`);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[13.5rem_minmax(0,1fr)] lg:bg-sidebar xl:grid-cols-[15rem_minmax(0,1fr)]">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-4 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col overflow-y-auto border-r border-border bg-sidebar px-4 lg:flex">
        <Link href="/dashboard" aria-label="Tradeo dashboard" className="my-4 ml-1 self-start rounded-lg">
          <Wordmark />
        </Link>
        <div className="mt-3 mb-6">
          <Navigation pathname={pathname} />
        </div>
        <div className="mt-auto pb-4"><SessionControls mode={mode} /></div>
      </aside>

      <div className="min-w-0 bg-background">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-2 border-b border-border bg-background/95 px-4 backdrop-blur sm:px-6 xl:px-8">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <div className="lg:hidden">
              <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
                <DialogTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label="Open navigation"><Menu aria-hidden /></Button>
                </DialogTrigger>
                <DialogContent className="inset-y-0 left-0 top-0 flex h-dvh max-h-none w-[min(19rem,calc(100%-2rem))] max-w-none translate-x-0 translate-y-0 flex-col rounded-none border-y-0 border-l-0 bg-sidebar p-4">
                  <DialogTitle className="sr-only">Workspace navigation</DialogTitle>
                  <DialogDescription className="sr-only">Go to a Tradeo workspace page.</DialogDescription>
                  <div className="mb-5 self-start"><Wordmark /></div>
                  <Navigation pathname={pathname} onNavigate={() => setMenuOpen(false)} />
                  <div className="mt-auto"><SessionControls mode={mode} /></div>
                </DialogContent>
              </Dialog>
            </div>
            <Link href="/dashboard" aria-label="Tradeo dashboard" className="rounded-lg sm:hidden"><Wordmark compact /></Link>
            <div aria-label="Current page" className="hidden min-w-0 items-center gap-2 text-sm sm:flex">
              <span className="text-muted-foreground">Workspace</span>
              <ChevronRight aria-hidden className="size-3.5 text-muted-foreground" />
              <span className="truncate font-medium">{activeRoute?.title ?? "Tradeo"}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <Status tone="accent" dot>Preview</Status>
            <div className="mx-1 hidden h-5 w-px bg-border sm:block" />
            <ThemeToggle />
            <Button asChild variant="ghost" size="icon" className="hidden sm:inline-flex">
              <Link href="/alerts" aria-label="Open alerts" title="Open alerts"><Bell aria-hidden /></Link>
            </Button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="mx-auto max-w-400 px-4 py-6 outline-none sm:px-6 sm:py-7 xl:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
