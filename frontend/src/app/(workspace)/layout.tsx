import { WorkspaceShell } from "@/components/workspace-shell";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  await requirePreviewSession();
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
