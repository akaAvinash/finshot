import type { Metadata } from "next";
import { Brokers } from "@/components/brokers/brokers";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Brokers" };

export default async function BrokersPage() {
  const { mode } = await requireWorkspaceSession();
  return <Brokers mode={mode} />;
}
