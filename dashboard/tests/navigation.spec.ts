import { test, expect, type Page } from "@playwright/test";
import type { Camera, Report, Run } from "../lib/types";

const cameras: Camera[] = [
  { id: "north", name: "North & Queen", city: "Toronto", country: "Canada", timezone: "America/Toronto", provider: "test", lat: 43.65, lon: -79.38, source_url: "https://example.com/north.jpg", stream_url: null, kind: "snapshot", feed_type: "snapshot", saved: true, gate: [.1, .5, .9, .5], roi: [0, 0, 1, 1], confidence: .3 },
  { id: "south", name: "South Street", city: "London", country: "United Kingdom", timezone: "Europe/London", provider: "test", lat: 51.5, lon: -.12, source_url: "https://example.com/south.jpg", stream_url: null, kind: "snapshot", feed_type: "snapshot", saved: false, gate: [.1, .5, .9, .5], roi: [0, 0, 1, 1], confidence: .3 },
  { id: "video", name: "Video Street", city: "London", country: "United Kingdom", timezone: "Europe/London", provider: "test", lat: 51.51, lon: -.11, source_url: "https://example.com/video.jpg", stream_url: "https://example.com/video.mp4", kind: "video", feed_type: "clip", saved: false, gate: [.1, .5, .9, .5], roi: [0, 0, 1, 1], confidence: .3 },
];
const archivedRun: Run = {
  id: "archived", camera_id: "south", camera_name: "South Street", camera_timezone: "Europe/London",
  status: "completed", created_at: "2026-11-09T08:00:00Z", finished_at: "2026-11-09T08:00:30Z", progress: 1, error: null,
  frame_url: "/api/runs/archived/frame", detections: [], options: { mode: "snapshot", duration: 30, interval: 5 },
  metrics: { mode: "snapshot", visible_mean: 12.5, visible_peak: 15, occupancy_mean: 8.25, crossings: null, flow_per_second: null, flow_per_minute: null, duration: 30, frames: 6, sampling_fps: null, class_counts: { car: 12.5 }, direction: null, confidence_mean: .9, unchanged_samples: 0, source_age_seconds: null, source_modified: null, note: "Archived observation." },
  samples: [{ elapsed: 0, visible: 12, occupancy: 8, crossings: 0, counts: { car: 12 } }],
};
const recentRun: Run = { ...archivedRun, id: "recent", camera_id: "north", camera_name: "North & Queen", frame_url: null, metrics: { ...archivedRun.metrics!, visible_mean: 2 } };
const report: Report = {
  runs: [archivedRun], limited: false,
  hourly: Array.from({ length: 24 }, (_, hour) => ({ hour, runs: hour === 8 ? 1 : 0, visible: hour === 8 ? 12.5 : hour === 9 ? 0 : null, occupancy: hour === 8 ? 8.25 : null, flow: null })),
};

async function fixture(page: Page) {
  await page.route(/^https:\/\//, route => route.abort());
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/snapshot") || path.endsWith("/frame")) {
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#233c31"/></svg>' });
    }
    const body = path === "/api/health" ? { status: "ok", model_ready: true, cameras: 3, runs: { completed: 2 }, scheduler: "running" }
      : path === "/api/cameras" ? { items: cameras, total: cameras.length }
      : path === "/api/providers" ? [{ id: "test", name: "Test network", count: 3 }]
      : path === "/api/schedules" ? []
      : path === "/api/runs" ? [recentRun]
      : path === "/api/runs/archived" ? archivedRun
      : path === "/api/runs/recent" ? recentRun
      : path === "/api/reports" ? report : null;
    return route.fulfill({ status: body === null ? 404 : 200, json: body ?? { detail: "Unavailable test feed." } });
  });
}

test.beforeEach(async ({ page }) => fixture(page));

test("camera filters and monitor survive refresh and browser navigation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Filter by feed type").selectOption("all");
  await page.getByLabel("Search cameras").fill("  South Street  ");
  await expect(page.locator(".result-count")).toHaveText("1 cameras");
  await page.locator(".camera-item-main").click();
  await page.getByRole("button", { name: "Open monitor", exact: true }).click();
  await expect(page).toHaveURL(/camera=south/);
  await page.reload();
  await expect(page.locator(".monitor-panel h2")).toHaveText("South Street");
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Camera explorer." })).toBeVisible();
  await expect(page.getByLabel("Search cameras")).toHaveValue("  South Street  ");
  await expect(page.getByLabel("Filter by feed type")).toHaveValue("all");
  await page.goForward();
  await expect(page.locator(".monitor-panel h2")).toHaveText("South Street");
  expect(errors).toEqual([]);
});

test("reset filters recovers from an empty search on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?view=cameras&feed=snapshot&country=Canada&network=test&saved=1&q=Missing");
  await expect(page.getByText("No cameras found", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Show all cameras", exact: true }).click();
  await expect(page.locator(".result-count")).toHaveText("3 cameras");
  await expect(page.getByLabel("Search cameras")).toHaveValue("");
  await expect(page.getByLabel("Filter by feed type")).toHaveValue("all");
  await expect(page.getByRole("button", { name: "Saved cameras", exact: true })).toHaveAttribute("aria-pressed", "false");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("historical observations open independently of the latest 200 runs", async ({ page }) => {
  await page.goto("/?view=reports&days=30&report_camera=south");
  await page.getByRole("button", { name: "View analysis of South Street", exact: true }).click();
  await expect(page).toHaveURL(/run=archived/);
  await expect(page.locator(".monitor-panel h2")).toHaveText("South Street");
  await expect(page.locator(".stats-grid .stat-card").nth(1).locator(".stat-number")).toContainText("12.5");
  await page.reload();
  await expect(page.locator(".stats-grid .stat-card").nth(1).locator(".stat-number")).toContainText("12.5");
  await page.goBack();
  await expect(page.getByRole("combobox", { name: "Period", exact: true })).toHaveValue("30");
  await expect(page.getByRole("combobox", { name: "Camera", exact: true })).toHaveValue("south");
});

test("report filters clear old results while loading and retry after errors", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let attempts = 0;
  await page.route("**/api/reports?**", async route => {
    if (new URL(route.request().url()).searchParams.get("days") !== "30") return route.fulfill({ json: report });
    attempts++;
    if (attempts === 1) { await gate; return route.fulfill({ status: 503, json: { detail: "Temporary report failure" } }); }
    return route.fulfill({ json: { ...report, runs: [], hourly: [] } });
  });
  await page.goto("/?view=reports");
  await expect(page.locator(".report-count strong")).toHaveText("1");
  await page.getByRole("combobox", { name: "Period", exact: true }).selectOption("30");
  await expect(page.locator(".report-count strong")).toHaveText("—");
  await expect(page.getByRole("button", { name: "View analysis of South Street" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Export CSV", exact: true })).toHaveAttribute("href", "/api/export.csv?days=30");
  release();
  await expect(page.locator("main").getByRole("alert")).toContainText("Temporary report failure");
  await expect(page.getByText("No analyses yet", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Retry report", exact: true }).click();
  await expect(page.getByText("No observations in this period", { exact: true })).toBeVisible();
  await expect(page.locator(".report-count strong")).toHaveText("0");
});

test("report data keeps fractional averages and distinguishes zero from missing data", async ({ page }) => {
  await page.goto("/?view=reports");
  await page.getByText("View measurement data", { exact: true }).click();
  const table = page.locator(".chart-data table");
  await expect(table.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "08:00", exact: true }) })).toContainText("12.5");
  await expect(table.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "09:00", exact: true }) }).getByRole("cell").first()).toHaveText("0");
  await expect(table.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "10:00", exact: true }) })).toContainText("No observation");
  await page.getByRole("combobox", { name: "Measurement", exact: true }).selectOption("flow");
  await expect(page.getByText("No measurements for this metric", { exact: true })).toBeVisible();
  await expect(page.getByText(/Vehicle flow requires video line-crossing analyses/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Measurement", exact: true })).toHaveValue("flow");
});

test("invalid URL choices fall back to supported dashboard settings", async ({ page }) => {
  await page.goto("/?view=unknown&feed=invalid&days=-50&metric=invalid");
  await expect(page.getByRole("heading", { name: "Traffic overview." })).toBeVisible();
  await page.getByRole("button", { name: "Traffic reports", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Period", exact: true })).toHaveValue("7");
  await expect(page.getByRole("combobox", { name: "Measurement", exact: true })).toHaveValue("visible");
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await expect(page.getByLabel("Filter by feed type")).toHaveValue("video");
});

test("video analysis cannot inherit a zero-second snapshot duration", async ({ page }) => {
  let submitted: { mode: string; duration: number } | null = null;
  await page.route("**/api/cameras/video/analyze", async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ json: { id: "queued", status: "queued" } });
  });
  await page.goto("/?camera=video");
  await page.getByLabel("Analysis mode").selectOption("snapshot");
  await page.getByLabel("Observation duration").selectOption("0");
  await page.getByLabel("Analysis mode").selectOption("video");
  await expect(page.getByLabel("Observation duration")).toHaveValue("30");
  await page.getByRole("button", { name: "Run analysis", exact: true }).click();
  await expect.poll(() => submitted).toMatchObject({ mode: "video", duration: 30 });
});

test("dialogs have accessible names and restore focus after Escape", async ({ page }) => {
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Understanding the metrics", exact: true });
  await trigger.click();
  await expect(page.getByRole("dialog", { name: "Understanding the measurements", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
