import type { ReactNode } from "react";

export function PageHeading({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-5 gap-y-4">
      <div>
        <h1 className="text-3xl font-semibold tracking-[-0.055em] sm:text-[2.375rem] sm:leading-[1.12]">{title}</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{description}</p>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}
