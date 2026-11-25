import type { Metadata } from "next";
import { Settings } from "@/components/settings/settings";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  await requirePreviewSession();
  return <Settings />;
}
