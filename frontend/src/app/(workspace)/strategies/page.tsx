import type { Metadata } from "next";
import { Strategies } from "@/components/strategies/strategies";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Strategies" };

export default async function StrategiesPage() {
  const { mode } = await requireWorkspaceSession();
  return <Strategies mode={mode} />;
}
