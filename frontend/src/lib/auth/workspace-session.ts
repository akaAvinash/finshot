import "server-only";

import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { readAuthConfig } from "./config";
import { hasPreviewSession } from "./preview-session";
import { authCookieHeader, requestUpstreamAuth, sessionCookie } from "./upstream";

type WorkspaceSession =
  | { mode: "preview"; signedIn: boolean }
  | { mode: "unavailable"; signedIn: false }
  | { mode: "staging"; signedIn: false }
  | { mode: "staging"; signedIn: true; totpEnabled: boolean };

export const getWorkspaceSession = cache(async (): Promise<WorkspaceSession> => {
  const cookieStore = await cookies();
  const config = readAuthConfig();
  if (config.mode === "preview") return { mode: config.mode, signedIn: await hasPreviewSession() };
  if (config.mode === "unavailable") return { mode: config.mode, signedIn: false };

  if (!cookieStore.has(sessionCookie)) return { mode: config.mode, signedIn: false };

  try {
    const cookie = authCookieHeader((name) => name === sessionCookie ? cookieStore.get(name)?.value : undefined);
    const response = await requestUpstreamAuth(config.upstream, "me", { headers: { Cookie: cookie } });
    if (response.status === 401) return { mode: config.mode, signedIn: false };
    if (response.status === 200) {
      const payload = await response.json();
      if (typeof payload?.user?.id === "string" && typeof payload.user.totpEnabled === "boolean" && typeof payload?.session?.expiresAt === "string") {
        return { mode: config.mode, signedIn: true, totpEnabled: payload.user.totpEnabled };
      }
    } else {
      await response.body?.cancel();
    }
  } catch {
    // Deny workspace access while the auth service cannot validate the session.
  }
  return { mode: "unavailable", signedIn: false };
});

export async function requireWorkspaceSession() {
  const session = await getWorkspaceSession();
  if (!session.signedIn) redirect("/login");
  if (session.mode === "staging" && !session.totpEnabled) redirect("/login/authenticator");
  return session;
}
