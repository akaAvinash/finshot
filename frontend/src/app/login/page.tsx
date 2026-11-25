import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getWorkspaceSession } from "@/lib/auth/workspace-session";
import { LoginForm } from "./login-form";
import { LoginFrame } from "./login-frame";
import { StagingLoginForm } from "./staging-login-form";

export const metadata: Metadata = { title: "Sign-in" };

export default async function LoginPage() {
  const session = await getWorkspaceSession();
  if (session.signedIn) {
    redirect(session.mode === "staging" && !session.totpEnabled ? "/login/authenticator" : "/dashboard");
  }

  const preview = session.mode === "preview";
  return <LoginFrame preview={preview} title={preview ? "Preview sign-in" : "Staging sign-in"}>
    {session.mode === "unavailable" ? <p role="alert" className="mt-2 text-sm leading-relaxed text-negative">
      Sign-in is temporarily unavailable. Reload to try again.
    </p> : preview ? <>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Use any sample Indian mobile number to open the simulated workspace. No SMS will be sent.</p>
      <LoginForm />
    </> : <StagingLoginForm />}
  </LoginFrame>;
}
