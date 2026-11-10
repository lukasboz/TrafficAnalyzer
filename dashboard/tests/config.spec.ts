import { test, expect } from "@playwright/test";
import { backendConfiguration, workspaceConfiguration } from "../lib/server/config";
import { dashboardReturnTo, signInPath } from "../lib/navigation";

const key = "test-key-with-at-least-thirty-two-characters";
const base = { ANALYSIS_URL: "https://analysis.example.com", ANALYSIS_KEY: key };
test("sign-in return links preserve the dashboard and reject external destinations", () => {
  const destination = "/?view=cameras&country=Canada&q=North%20%26%20Queen#main";
  expect(dashboardReturnTo(destination)).toBe(destination);
  expect(signInPath(destination)).toBe("/login?next=" + encodeURIComponent(destination));
  expect(signInPath("/")).toBe("/login");
  for (const value of ["https://evil.example", "//evil.example", "/\\evil.example", "/api/auth/logout", "/login", "javascript:alert(1)", [destination], undefined]) {
    expect(dashboardReturnTo(value)).toBe("/");
  }
});
test("missing backend configuration is explicit", () => {
  expect(() => backendConfiguration({})).toThrow("Set ANALYSIS_URL");
  expect(() => backendConfiguration({ ANALYSIS_URL: base.ANALYSIS_URL })).toThrow("Set ANALYSIS_KEY");
});
test("backend origin rejects credentials, unsupported schemes and API paths", () => {
  for (const url of ["file:///data", "https://user:password@analysis.example.com", "https://analysis.example.com/api", "https://analysis.example.com?key=secret"]) {
    expect(() => backendConfiguration({ ...base, ANALYSIS_URL: url })).toThrow();
  }
});
test("Vercel rejects loopback, HTTP and temporary tunnels", () => {
  for (const url of ["http://analysis.example.com", "https://localhost", "https://127.0.0.1:8000", "https://[::1]:8000", "https://expired.trycloudflare.com", "https://expired.loca.lt"]) {
    expect(() => backendConfiguration({ ...base, ANALYSIS_URL: url, VERCEL: "1" })).toThrow("permanent public HTTPS");
  }
  expect(backendConfiguration({ ...base, VERCEL: "1" }).url.origin).toBe(base.ANALYSIS_URL);
});
test("production sign-in is required and local bypass cannot override Vercel", () => {
  expect(() => workspaceConfiguration({ ...base, VERCEL: "1", FLOWSTATE_LOCAL: "1" })).toThrow("DASHBOARD_PASSWORD");
  expect(() => workspaceConfiguration({ ...base, NODE_ENV: "production" })).toThrow("DASHBOARD_PASSWORD");
  expect(workspaceConfiguration({ ...base, VERCEL: "1", DASHBOARD_PASSWORD: "long-workspace-password" }).signInEnabled).toBe(true);
});
test("local production mode is restricted to loopback", () => {
  expect(workspaceConfiguration({ ...base, ANALYSIS_URL: "http://127.0.0.1:8000", FLOWSTATE_LOCAL: "1", NODE_ENV: "production" }).signInEnabled).toBe(false);
  expect(() => workspaceConfiguration({ ...base, FLOWSTATE_LOCAL: "1", NODE_ENV: "production" })).toThrow("DASHBOARD_PASSWORD");
});
