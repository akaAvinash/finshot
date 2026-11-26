import type { Metadata } from "next";
import { Markets } from "@/components/markets/markets";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Markets" };

export default async function MarketsPage() {
  const { mode } = await requireWorkspaceSession();
  return <Markets mode={mode} />;
}
