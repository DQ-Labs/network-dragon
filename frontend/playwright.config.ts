import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "../tests/browser",
  outputDir: "../artifacts/browser",
  use: {
    baseURL: process.env.DRAGON_TEST_BASE_URL || "http://127.0.0.1:8000",
    browserName: "chromium",
    screenshot: "only-on-failure",
  },
  reporter: "list",
  workers: 1,
});
