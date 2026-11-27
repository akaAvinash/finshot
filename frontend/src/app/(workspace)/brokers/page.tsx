import type { Metadata } from "next";
import { Brokers } from "@/components/brokers/brokers";
import { BrokerConnections } from "@/components/brokers/broker-connections";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Brokers" };

export default async function BrokersPage() {
  const { mode } = await requireWorkspaceSession();
  return mode === "staging" ? <BrokerConnections /> : <Brokers />;
}
