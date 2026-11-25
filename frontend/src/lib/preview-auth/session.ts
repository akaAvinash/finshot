import "server-only";

// Keep phase branches that still import this guard on the configured auth mode.
export { requireWorkspaceSession as requirePreviewSession } from "@/lib/auth/workspace-session";
