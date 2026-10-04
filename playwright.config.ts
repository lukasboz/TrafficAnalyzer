import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "./tests", timeout: 90000, expect: { timeout: 20000 }, workers: 1, use: { baseURL: "http://127.0.0.1:3000", headless: true, viewport: { width: 1440, height: 1100 }, screenshot: "only-on-failure" } });
