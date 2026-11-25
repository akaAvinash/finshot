import type { Metadata } from "next";
import { Settings } from "@/components/settings/settings";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const { mode } = await requireWorkspaceSession();
  return <Settings accountAlerts={mode === "staging"} />;
}
