import { describe, expect, it } from "vitest";
import { demoAuthorizationPath, parseBrokerCallback } from "@/lib/api/broker-connections-client";

const origin = "https://demo.example";
const state = "synthetic-state-123456";
const callback = `/brokers/callback?state=${state}&code=demo`;

describe("demo broker authorization", () => {
  it("keeps redirects on the app’s callback page", () => {
    expect(demoAuthorizationPath(callback, origin)).toBe(callback);
    expect(demoAuthorizationPath(`${origin}${callback}`, origin)).toBe(callback);
    expect(demoAuthorizationPath(`https://other.example${callback}`, origin)).toBeUndefined();
    expect(demoAuthorizationPath(`/other?state=${state}`, origin)).toBeUndefined();
  });

  it("preserves provider values and rejects duplicate callback parameters", () => {
    expect(parseBrokerCallback(new URLSearchParams(`state=${state}&code=demo%2Bvalue`)))
      .toEqual({ state, params: { code: "demo+value" } });
    expect(parseBrokerCallback(new URLSearchParams(`state=${state}&state=${state}`))).toBeUndefined();
    expect(parseBrokerCallback(new URLSearchParams(`state=${state}&code=a&code=b`))).toBeUndefined();
  });
});
