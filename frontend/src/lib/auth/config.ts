import "server-only";

export type AuthMode = "preview" | "staging";

type AuthConfig =
  | { mode: "preview" }
  | { mode: "staging"; upstream: string; publicOrigin: string; ingressToken: string; testerSignInEnabled: boolean }
  | { mode: "unavailable" };

function readOrigin(value: string | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) return null;
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : null;
  } catch {
    return null;
  }
}

function isProtectedOrigin(origin: string | null): origin is string {
  if (!origin) return false;
  return origin.startsWith("https:") || /^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(origin);
}

export function readAuthConfig(): AuthConfig {
  const mode = process.env.TRADEO_AUTH_MODE ?? "preview";
  if (mode === "preview") return { mode };

  const upstream = readOrigin(process.env.TRADEO_API_ORIGIN);
  const publicOrigin = readOrigin(process.env.TRADEO_PUBLIC_ORIGIN);
  const ingressToken = process.env.TRADEO_AUTH_INGRESS_TOKEN;
  if (mode !== "staging" || !isProtectedOrigin(upstream) || !isProtectedOrigin(publicOrigin) || upstream === publicOrigin ||
      !ingressToken || !/^[A-Za-z0-9_-]{43,128}$/.test(ingressToken)) {
    return { mode: "unavailable" };
  }

  return { mode, upstream, publicOrigin, ingressToken, testerSignInEnabled: process.env.TRADEO_TESTER_SIGN_IN_ENABLED === "true" };
}
