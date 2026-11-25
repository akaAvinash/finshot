import type { Metadata } from "next";
import { Markets } from "@/components/markets/markets";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Markets" };

export default async function MarketsPage() {
  await requireWorkspaceSession();
  return <Markets />;
}
