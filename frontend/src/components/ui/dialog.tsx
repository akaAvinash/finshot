"use client";

import type { ComponentProps } from "react";
import { X } from "lucide-react";
import { Dialog as Primitive } from "radix-ui";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;

export function DialogContent({ className, children, ...props }: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Overlay className="fixed inset-0 z-40 bg-black/65" />
      <Primitive.Content
        data-slot="dialog-content"
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-2xl",
          className,
        )}
        {...props}
      >
        {children}
        <Primitive.Close asChild>
          <Button size="icon" variant="ghost" aria-label="Close dialog" className="absolute right-3 top-3">
            <X aria-hidden />
          </Button>
        </Primitive.Close>
      </Primitive.Content>
    </Primitive.Portal>
  );
}

export function DialogTitle({ className, ...props }: ComponentProps<typeof Primitive.Title>) {
  return <Primitive.Title className={cn("pr-10 text-xl font-semibold tracking-tight", className)} {...props} />;
}

export function DialogDescription({ className, ...props }: ComponentProps<typeof Primitive.Description>) {
  return <Primitive.Description className={cn("mt-2 text-sm leading-relaxed text-muted-foreground", className)} {...props} />;
}
