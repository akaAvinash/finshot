import { randomBytes } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readAuthConfig } from "@/lib/auth/config";
import { getTrustedClientIp } from "@/lib/auth/ingress";

vi.mock("server-only", () => ({}));

const ingressToken = randomBytes(32).toString("base64url");

describe("staging auth config", () => {
  beforeEach(() => {
    vi.stubEnv("TRADEO_AUTH_MODE", "staging");
    vi.stubEnv("TRADEO_API_ORIGIN", "https://auth.example.internal");
    vi.stubEnv("TRADEO_PUBLIC_ORIGIN", "https://tradeo.example.internal");
    vi.stubEnv("TRADEO_AUTH_INGRESS_TOKEN", ingressToken);
  });

  afterEach(() => { vi.unstubAllEnvs(); });

  it("accepts HTTPS and loopback HTTP on either hop", () => {
    expect(readAuthConfig().mode).toBe("staging");
    vi.stubEnv("TRADEO_API_ORIGIN", "http://127.0.0.1:3102");
    vi.stubEnv("TRADEO_PUBLIC_ORIGIN", "http://localhost:3101");
    expect(readAuthConfig().mode).toBe("staging");
  });

  it("fails closed with non-loopback HTTP or an unconfigured ingress", () => {
    vi.stubEnv("TRADEO_API_ORIGIN", "http://auth.example.internal");
    expect(readAuthConfig().mode).toBe("unavailable");
    vi.stubEnv("TRADEO_API_ORIGIN", "https://auth.example.internal");
    vi.stubEnv("TRADEO_AUTH_INGRESS_TOKEN", "too-short");
    expect(readAuthConfig().mode).toBe("unavailable");
  });

  it("requires an explicit opt-in for tester sign-in", () => {
    vi.stubEnv("TRADEO_TESTER_SIGN_IN_ENABLED", undefined);
    expect(readAuthConfig()).toMatchObject({ mode: "staging", testerSignInEnabled: false });
    vi.stubEnv("TRADEO_TESTER_SIGN_IN_ENABLED", "true");
    expect(readAuthConfig()).toMatchObject({ mode: "staging", testerSignInEnabled: true });
  });
});

it("accepts a single IP only with valid ingress proof", () => {
  const headers = new Headers({ "X-Forwarded-For": "192.0.2.9", "X-Tradeo-Client-IP": "2001:db8::9" });
  expect(getTrustedClientIp(headers, ingressToken)).toBeNull();
  headers.set("X-Tradeo-Ingress-Token", randomBytes(32).toString("base64url"));
  expect(getTrustedClientIp(headers, ingressToken)).toBeNull();
  headers.set("X-Tradeo-Ingress-Token", ingressToken);
  expect(getTrustedClientIp(headers, ingressToken)).toBe("2001:db8::9");
  headers.set("X-Tradeo-Client-IP", "192.0.2.9, 192.0.2.10");
  expect(getTrustedClientIp(headers, ingressToken)).toBeNull();
});
