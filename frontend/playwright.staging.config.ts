import { defineConfig, devices } from "@playwright/test";

const baseURL = "http://127.0.0.1:3101";
const upstream = "http://127.0.0.1:3102";

export default defineConfig({
  testDir: "./tests/staging",
  outputDir: "./.next/staging-test-results",
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL },
  webServer: [
    { command: "node tests/staging/auth-fixture.mjs", url: `${upstream}/health`, reuseExistingServer: false },
    {
      command: "npm run start -- --hostname 127.0.0.1 --port 3101",
      url: `${baseURL}/login`,
      timeout: 60_000,
      reuseExistingServer: false,
      env: { TRADEO_AUTH_MODE: "staging", TRADEO_API_ORIGIN: upstream, TRADEO_PUBLIC_ORIGIN: baseURL },
    },
  ],
});
