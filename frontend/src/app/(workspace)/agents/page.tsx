import type { Metadata } from "next";
import { Agents } from "@/components/agents/agents";
import { StagingAgents } from "@/components/agents/staging-agents";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Agents" };

export default async function AgentsPage() {
  const { mode } = await requireWorkspaceSession();
  return mode === "staging" ? <StagingAgents /> : <Agents />;
}
