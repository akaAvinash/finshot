import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AccountSettings } from "@/components/settings/account-settings";
import { Settings } from "@/components/settings/settings";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const session = await requireWorkspaceSession();
  if (session.mode === "staging" && session.tester) redirect("/dashboard");
  return session.mode === "staging" ? <AccountSettings /> : <Settings />;
}
