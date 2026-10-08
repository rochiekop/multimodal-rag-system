import { defineConfig, devices } from "@playwright/test"

// Runs against an already-running app (npm run build && npm start) and backend stack.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === "1",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
