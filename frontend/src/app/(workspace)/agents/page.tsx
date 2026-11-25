import type { Metadata } from "next";
import { Agents } from "@/components/agents/agents";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Agents" };

export default async function AgentsPage() {
  await requirePreviewSession();
  return <Agents />;
}
