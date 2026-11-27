import type { ReactNode } from "react";
import { WorkspaceShellClient } from "@/components/workspace-shell-client";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export async function WorkspaceShell({ children }: { children: ReactNode }) {
  const session = await requireWorkspaceSession();
  return <WorkspaceShellClient mode={session.mode} tester={session.mode === "staging" && session.tester}>{children}</WorkspaceShellClient>;
}
