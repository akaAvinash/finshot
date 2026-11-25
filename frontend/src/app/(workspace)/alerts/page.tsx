import type { Metadata } from "next";
import { Alerts } from "@/components/alerts/alerts";
import { AccountAlerts } from "@/components/alerts/account-alerts";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Alerts" };

export default async function AlertsPage() {
  const { mode } = await requireWorkspaceSession();
  return mode === "staging" ? <AccountAlerts /> : <Alerts />;
}
