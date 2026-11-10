import { test, expect } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const origin = "http://127.0.0.1:3100";
const password = "test-workspace-password-2026";
const key = readFileSync(path.resolve("../.runtime/service.key"), "utf8").trim();
let server: ChildProcess | undefined;

async function start(environment: Record<string, string> = {}) {
  server = spawn(process.execPath, [path.resolve("node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", "3100"], {
    cwd: process.cwd(), windowsHide: true, stdio: "ignore",
    env: { ...process.env, NODE_ENV: "production", ANALYSIS_URL: "http://127.0.0.1:8000", ANALYSIS_KEY: key, DASHBOARD_PASSWORD: "", FLOWSTATE_LOCAL: "1", ...environment },
  });
  await expect.poll(async () => {
    if (server?.exitCode != null) throw new Error("Production dashboard exited before it was ready.");
    return fetch(origin + "/api/health").then(r => r.status).catch(() => 0);
  }, { timeout: 30000 }).not.toBe(0);
}
test.afterEach(async () => {
  if (server && server.exitCode == null) {
    const exited = new Promise<void>(resolve => server!.once("exit", () => resolve()));
    server.kill();
    await exited;
  }
  server = undefined;
});

test("production sign-in protects the workspace and persists until sign-out", async ({ page, request }) => {
  await start({ DASHBOARD_PASSWORD: password });
  const blocked = await request.get(origin + "/api/health");
  expect(blocked.status()).toBe(401);
  expect((await blocked.json()).code).toBe("SIGN_IN_REQUIRED");
  const crossOrigin = await request.post(origin + "/api/auth/login", { headers: { Origin: "https://unrelated.example" }, data: { password } });
  expect(crossOrigin.status()).toBe(403);
  await page.goto(origin);
  await expect(page).toHaveURL(origin + "/login");
  await page.getByLabel("Workspace password").fill("wrong-workspace-password");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page.locator(".signin-form").getByRole("alert")).toContainText("incorrect");
  await page.getByLabel("Workspace password").fill(password);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page).toHaveURL(origin + "/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await expect(page.locator(".monitor-panel")).toBeVisible();
  const session = (await page.context().cookies()).find(c => c.name === "flowstate_session")!;
  expect(session.httpOnly).toBe(true);
  expect(session.sameSite).toBe("Lax");
  await page.reload();
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await page.screenshot({ path: "../.runtime/next-production.png", fullPage: true });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(origin + "/login");
  expect((await page.request.get(origin + "/api/health")).status()).toBe(401);
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  // Flip an unused trailing base64 bit: decoded bytes stay identical, but
  // the altered signature must still be rejected as noncanonical.
  const changedTail = alphabet[alphabet.indexOf(session.value.at(-1)!) + 1];
  await page.context().addCookies([{ ...session, value: session.value.slice(0, -1) + changedTail }]);
  expect((await page.request.get(origin + "/api/health")).status()).toBe(401);
});

test("saved report links survive sign-in and external return targets are rejected", async ({ page }) => {
  await start({ DASHBOARD_PASSWORD: password });
  const destination = "/?view=reports&days=30&metric=occupancy";
  await page.goto(origin + destination);
  await expect(page).toHaveURL(origin + "/login?next=" + encodeURIComponent(destination));
  await page.getByLabel("Workspace password").fill(password);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page).toHaveURL(origin + destination);
  await expect(page.getByRole("combobox", { name: "Period", exact: true })).toHaveValue("30");
  await expect(page.getByRole("combobox", { name: "Measurement", exact: true })).toHaveValue("occupancy");
  await page.goto(origin + "/login?next=" + encodeURIComponent("//external.example"));
  await expect(page).toHaveURL(origin + "/");
});

test("missing settings show configuration guidance", async ({ page, request }) => {
  await start({ ANALYSIS_URL: "", ANALYSIS_KEY: "" });
  const response = await request.get(origin + "/api/health");
  expect(response.status()).toBe(503);
  expect((await response.json()).code).toBe("BACKEND_NOT_CONFIGURED");
  await page.goto(origin);
  await expect(page.getByRole("heading", { name: "Connect your workspace" })).toBeVisible();
  await expect(page.locator(".signin-card").getByRole("alert")).toContainText("ANALYSIS_URL");
  await page.goto(origin + "/login");
  await expect(page.getByRole("heading", { name: "Connect your workspace" })).toBeVisible();
  const login = await request.post(origin + "/api/auth/login", { headers: { Origin: origin }, data: { password } });
  expect(login.status()).toBe(503);
  expect((await login.json()).code).toBe("BACKEND_NOT_CONFIGURED");
});

test("unreachable backend reports a connection failure", async ({ request }) => {
  await start({ ANALYSIS_URL: "http://127.0.0.1:9" });
  const response = await request.get(origin + "/api/health");
  expect(response.status()).toBe(503);
  expect((await response.json()).code).toBe("BACKEND_UNREACHABLE");
});

test("mismatched backend key reports the actual problem", async ({ request }) => {
  await start({ ANALYSIS_KEY: "incorrect-service-key-at-least-thirty-two-characters" });
  const response = await request.get(origin + "/api/health");
  expect(response.status()).toBe(502);
  const result = await response.json();
  expect(result.code).toBe("BACKEND_KEY_REJECTED");
  expect(result.detail).toContain("FLOWSTATE_API_KEY");
  expect(result.detail).not.toContain(key);
});
