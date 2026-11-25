import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getWorkspaceSession } from "@/lib/auth/workspace-session";
import { LoginFrame } from "../login-frame";
import { AuthenticatorSetup } from "./setup-form";

export const metadata: Metadata = { title: "Authenticator setup" };

export default async function AuthenticatorPage() {
  const session = await getWorkspaceSession();
  if (session.mode !== "staging" || !session.signedIn) redirect("/login");
  if (session.totpEnabled) redirect("/dashboard");

  return <LoginFrame title="Set up your authenticator">
    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
      Add Tradeo to an authenticator app. You’ll use its six-digit codes to sign in next time.
    </p>
    <AuthenticatorSetup />
  </LoginFrame>;
}
