import { CircleAlert, Inbox, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function DataState({ title, description, action, error = false, icon: Icon = error ? CircleAlert : Inbox }: {
  title: string;
  description: string;
  action?: ReactNode;
  error?: boolean;
  icon?: LucideIcon;
}) {
  return (
    <Card role={error ? "alert" : undefined} className="flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center">
      <span className={cn("mb-4 grid size-11 place-items-center rounded-xl bg-surface-raised", error ? "text-negative" : "text-accent-foreground")}>
        <Icon aria-hidden className="size-5" />
      </span>
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </Card>
  );
}

export function DashboardSkeleton({ label = "Loading dashboard" }: { label?: string } = {}) {
  return (
    <div role="status" aria-label={label} className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <Card key={item} aria-hidden className="h-27 p-4">
            <div className="h-3 w-3/5 rounded bg-surface-raised motion-safe:animate-pulse" />
            <div className="mt-5 h-5 w-4/5 rounded bg-surface-raised motion-safe:animate-pulse" />
          </Card>
        ))}
      </div>
      <Card aria-hidden className="h-76 p-5">
        <div className="h-5 w-1/4 rounded bg-surface-raised motion-safe:animate-pulse" />
        <div className="mt-5 h-52 rounded bg-surface-raised motion-safe:animate-pulse" />
      </Card>
    </div>
  );
}
