import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const tones = {
  neutral: "bg-surface-raised text-muted-foreground",
  accent: "bg-primary/12 text-accent-foreground",
  positive: "bg-positive/12 text-positive",
  negative: "bg-negative/12 text-negative",
};

export function Status({ children, tone = "neutral", dot = false }: {
  children: ReactNode;
  tone?: keyof typeof tones;
  dot?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium", tones[tone])}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}
