import type { ReactNode } from "react";
import { WorkspaceShellClient } from "@/components/workspace-shell-client";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export async function WorkspaceShell({ children }: { children: ReactNode }) {
  const { mode } = await requireWorkspaceSession();
  return <WorkspaceShellClient mode={mode}>{children}</WorkspaceShellClient>;
}
