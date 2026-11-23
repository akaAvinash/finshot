"use client";

import type { ReactNode } from "react";
import { ThemeProvider } from "next-themes";
import { Notifications } from "@/components/ui/notifications";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" disableTransitionOnChange>
      <Notifications>{children}</Notifications>
    </ThemeProvider>
  );
}
