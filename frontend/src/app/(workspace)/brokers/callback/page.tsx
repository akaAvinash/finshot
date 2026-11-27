import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { BrokerCallbackPage } from "@/components/brokers/broker-callback";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Complete broker authorization", referrer: "no-referrer", robots: { index: false, follow: false } };

export default async function CallbackPage() {
  const session = await requireWorkspaceSession();
  if (session.mode !== "staging" || session.tester) redirect("/brokers");
  return <BrokerCallbackPage />;
}
