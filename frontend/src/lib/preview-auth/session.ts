import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

const cookieName = "tradeo-preview-session";
const previewValue = "phase-1";

// This cookie only gates public sample content in the frontend preview.
export async function hasPreviewSession() {
  return (await cookies()).get(cookieName)?.value === previewValue;
}

export async function requirePreviewSession() {
  if (!(await hasPreviewSession())) redirect("/login");
}

export async function startPreviewSession() {
  const requestHeaders = await headers();
  const secure = requestHeaders.get("x-forwarded-proto") === "https";

  (await cookies()).set(cookieName, previewValue, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: 8 * 60 * 60,
  });
}

export async function endPreviewSession() {
  (await cookies()).delete(cookieName);
}
