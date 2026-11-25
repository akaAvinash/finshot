import type { Metadata } from "next";
import { AccountSettings } from "@/components/settings/account-settings";
import { Settings } from "@/components/settings/settings";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const { mode } = await requireWorkspaceSession();
  return mode === "staging" ? <AccountSettings /> : <Settings />;
}
