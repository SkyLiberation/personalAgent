const path = require("path");
const { createRequire } = require("module");
const frontendRequire = createRequire(path.resolve(__dirname, "../frontend/package.json"));
const { defineConfig, devices } = frontendRequire("@playwright/test");

module.exports = defineConfig({
  testDir: __dirname,
  testMatch: /research-quality-frontend-e2e\.playwright\.spec\.cjs/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 480000,
  expect: {
    timeout: 30000,
  },
  use: {
    baseURL: process.env.PERSONAL_AGENT_FRONTEND_URL || "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
