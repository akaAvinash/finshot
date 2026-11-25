"use server";

import { redirect } from "next/navigation";
import { readAuthConfig } from "@/lib/auth/config";
import type { LoginState } from "@/lib/auth/browser-client";
import { endPreviewSession, startPreviewSession } from "@/lib/auth/preview-session";
import { normalizeIndianMobile } from "@/lib/preview-auth/validation";

export async function previewLogin(state: LoginState, formData: FormData): Promise<LoginState> {
  if (readAuthConfig().mode !== "preview") return { step: "phone", error: "Preview sign-in is disabled." };
  if (formData.get("intent") === "change-phone") return { step: "phone" };

  if (state.step === "phone") {
    const phone = normalizeIndianMobile(String(formData.get("phone") ?? ""));
    return phone ? { step: "code", phone } : {
      step: "phone",
      error: "Enter a valid 10-digit Indian mobile number.",
    };
  }

  if (String(formData.get("code") ?? "").trim() !== "123456") {
    return { ...state, error: "That code did not match. Use the preview code 123456." };
  }

  await startPreviewSession();
  redirect("/dashboard");
}

export async function signOut(): Promise<never> {
  if (readAuthConfig().mode === "preview") await endPreviewSession();
  redirect("/login");
}
