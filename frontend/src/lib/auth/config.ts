import "server-only";

export type AuthMode = "preview" | "staging";

type AuthConfig =
  | { mode: "preview" }
  | { mode: "staging"; upstream: string; publicOrigin: string }
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

export function readAuthConfig(): AuthConfig {
  const mode = process.env.TRADEO_AUTH_MODE ?? "preview";
  if (mode === "preview") return { mode };

  const upstream = readOrigin(process.env.TRADEO_API_ORIGIN);
  const publicOrigin = readOrigin(process.env.TRADEO_PUBLIC_ORIGIN);
  const secureOrigin = publicOrigin?.startsWith("https:") || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(publicOrigin ?? "");
  if (mode !== "staging" || !upstream || !publicOrigin || !secureOrigin || upstream === publicOrigin) {
    return { mode: "unavailable" };
  }

  return { mode, upstream, publicOrigin };
}
