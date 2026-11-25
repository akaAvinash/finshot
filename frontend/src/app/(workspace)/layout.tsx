import { WorkspaceShell } from "@/components/workspace-shell";
import { WorkspaceControlsProvider } from "@/components/workspace-controls-provider";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  await requirePreviewSession();
  return <WorkspaceControlsProvider><WorkspaceShell>{children}</WorkspaceShell></WorkspaceControlsProvider>;
}
