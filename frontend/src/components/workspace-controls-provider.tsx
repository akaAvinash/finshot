"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { createWorkspaceControlsMock } from "@/lib/api/workspace-controls-mock";
import type { WorkspaceControlsClient } from "@/lib/api/workspace-controls-types";

const WorkspaceControlsContext = createContext<WorkspaceControlsClient | null>(null);

export function WorkspaceControlsProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => createWorkspaceControlsMock());
  return <WorkspaceControlsContext.Provider value={client}>{children}</WorkspaceControlsContext.Provider>;
}

export function useWorkspaceControls() {
  const client = useContext(WorkspaceControlsContext);
  if (!client) throw new Error("Workspace controls require the preview workspace provider.");
  return client;
}
