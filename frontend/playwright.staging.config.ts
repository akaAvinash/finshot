import { randomBytes } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";

const baseURL = "http://127.0.0.1:3101";
const upstream = "http://127.0.0.1:3102";
const nextOrigin = "http://127.0.0.1:3103";
const ingressEnv = { TRADEO_AUTH_INGRESS_TOKEN: randomBytes(32).toString("base64url") };

export default defineConfig({
  testDir: "./tests/staging",
  outputDir: "./.next/staging-test-results",
  // The local auth fixture resets its shared state before each test.
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL },
  webServer: [
    { command: "node tests/staging/auth-fixture.mjs", url: `${upstream}/health`, reuseExistingServer: false, env: ingressEnv },
    {
      command: "npm run start -- --hostname 127.0.0.1 --port 3103",
      url: `${nextOrigin}/login`,
      timeout: 60_000,
      reuseExistingServer: false,
      env: { ...ingressEnv, TRADEO_AUTH_MODE: "staging", TRADEO_API_ORIGIN: upstream, TRADEO_PUBLIC_ORIGIN: baseURL, TRADEO_TESTER_SIGN_IN_ENABLED: "true" },
    },
  ],
});
