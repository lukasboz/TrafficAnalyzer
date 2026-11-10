import { test, expect, type Locator } from "@playwright/test";
import type { Camera, LiveFrame } from "../lib/types";

test.use({ deviceScaleFactor: 2 });

async function expectScreenResolution(canvas: Locator) {
  await expect.poll(() => canvas.evaluate((element: HTMLCanvasElement) => {
    const bounds = element.getBoundingClientRect();
    return Math.abs(element.width - bounds.width * window.devicePixelRatio) <= 1 && Math.abs(element.height - bounds.height * window.devicePixelRatio) <= 1;
  })).toBe(true);
}

test("video detection advances, pauses, resumes and follows saved geometry", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  const response = await page.request.get("/api/cameras?provider=caltrans&search=Hwy%205%20at%20Pocket");
  const cameras = (await response.json()).items as Camera[];
  const camera = cameras.find(camera => camera.kind === "video")!;
  expect(camera).toBeTruthy();
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Search cameras").fill(camera.name);
  await page.locator(".camera-item-main").first().click();
  await page.getByRole("button", { name: "Open monitor" }).click();
  const started = page.waitForResponse(response => response.url().endsWith("/live") && response.request().method() === "POST" && response.status() === 200);
  await page.getByRole("button", { name: "Live detection", exact: true }).click();
  const session = (await (await started).json()).session_id as string;
  const preview = page.getByTestId("live-preview");
  await expect(preview).toHaveAttribute("data-status", "playing", { timeout: 45000 });
  const canvas = page.getByLabel("Live camera feed with vehicle boxes, tracking trails, analysis area, and counting line");
  await expect(canvas).toBeVisible();
  await expectScreenResolution(canvas);
  const sequence = Number(await preview.getAttribute("data-sequence"));
  await expect.poll(async () => Number(await preview.getAttribute("data-sequence"))).toBeGreaterThan(sequence);
  const frame = await (await page.request.get("/api/live/" + session + "/frame")).json() as LiveFrame;
  expect(frame.image).toMatch(/^data:image\/jpeg;base64,/);
  expect(frame.gate).toEqual(camera.gate);
  for (const detection of frame.detections) {
    expect(detection.box).toHaveLength(4);
    expect(detection.track_id).toBeGreaterThan(0);
    expect(detection.trail?.length).toBeGreaterThan(0);
  }
  await page.getByLabel("Trails", { exact: true }).uncheck();
  await page.getByLabel("Labels", { exact: true }).uncheck();
  await page.getByLabel("Labels", { exact: true }).check();
  await page.getByLabel("Trails", { exact: true }).check();
  await page.screenshot({ path: "../.runtime/live-video.png", fullPage: true });
  const changedGate = [.2, .52, .8, .52];
  try {
    const patched = await page.request.patch("/api/cameras/" + camera.id, { headers: { Origin: "http://127.0.0.1:3000" }, data: { gate: changedGate } });
    expect(patched.status()).toBe(200);
    await expect.poll(async () => {
      const result = await page.request.get("/api/live/" + session + "/frame");
      return ((await result.json()) as LiveFrame).gate;
    }).toEqual(changedGate);
  } finally {
    await page.request.patch("/api/cameras/" + camera.id, { headers: { Origin: "http://127.0.0.1:3000" }, data: { gate: camera.gate } });
  }
  await expect.poll(async () => ((await (await page.request.get("/api/live/" + session + "/frame")).json()) as LiveFrame).gate).toEqual(camera.gate);
  const restoredSequence = Number(await preview.getAttribute("data-sequence"));
  await expect.poll(async () => Number(await preview.getAttribute("data-sequence"))).toBeGreaterThan(restoredSequence);
  await page.getByRole("button", { name: "Pause feed", exact: true }).click();
  await expect(preview).toHaveAttribute("data-status", "paused");
  await expect.poll(async () => (await page.request.get("/api/live/" + session + "/frame")).status()).toBe(410);
  // A frozen low-resolution source must still redraw sharp, aligned geometry
  // when the display changes, without a new backend frame or session.
  const pausedSequence = await preview.getAttribute("data-sequence");
  await page.setViewportSize({ width: 1200, height: 1000 });
  await expectScreenResolution(canvas);
  await page.getByRole("button", { name: "View camera fullscreen", exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true);
  await expectScreenResolution(canvas);
  expect(await preview.getAttribute("data-sequence")).toBe(pausedSequence);
  const gateIsAligned = await canvas.evaluate((element: HTMLCanvasElement, gate: number[]) => {
    const x = Math.round(gate[0] * element.width), y = Math.round(gate[1] * element.height);
    const pixel = element.getContext("2d")!.getImageData(x, y, 1, 1).data;
    return pixel[0] === 183 && pixel[1] === 239 && pixel[2] === 91;
  }, camera.gate);
  expect(gateIsAligned).toBe(true);
  await page.screenshot({ path: "../.runtime/live-fullscreen-retina.png" });
  await page.evaluate(() => document.exitFullscreen());
  await expectScreenResolution(canvas);
  const display = await page.context().newCDPSession(page);
  await display.send("Emulation.setDeviceMetricsOverride", { width: 1200, height: 1000, deviceScaleFactor: 3, mobile: false });
  await expect.poll(() => page.evaluate(() => window.devicePixelRatio)).toBe(3);
  await expectScreenResolution(canvas);
  expect(await preview.getAttribute("data-sequence")).toBe(pausedSequence);
  await display.detach();
  const resumed = page.waitForResponse(response => response.url().endsWith("/live") && response.request().method() === "POST" && response.status() === 200);
  await page.getByRole("button", { name: "Resume feed", exact: true }).click();
  const nextSession = (await (await resumed).json()).session_id as string;
  await expect(preview).toHaveAttribute("data-status", "playing", { timeout: 45000 });
  await page.getByRole("button", { name: "Camera image", exact: true }).click();
  await expect(preview).toHaveCount(0);
  await expect.poll(async () => (await page.request.get("/api/live/" + nextSession + "/frame")).status()).toBe(410);
  expect(errors).toEqual([]);
});

test("snapshot preview works on mobile and distinguishes stills from video", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Filter by feed type").selectOption("all");
  await page.getByLabel("Search cameras").fill("Inkoo");
  await page.locator(".camera-item-main").first().click();
  await page.getByRole("button", { name: "Open monitor" }).click();
  await page.getByRole("button", { name: "Snapshot detection", exact: true }).click();
  const canvas = page.getByLabel("Live camera feed with vehicle boxes, tracking trails, analysis area, and counting line");
  await expect(canvas).toBeVisible({ timeout: 45000 });
  await expectScreenResolution(canvas);
  await expect(page.getByText("REFRESHING SNAPSHOTS", { exact: true })).toBeVisible();
  await expect(page.getByText("Video required", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: "../.runtime/live-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Pause feed", exact: true }).click();
  await expect(page.getByTestId("live-preview")).toHaveAttribute("data-status", "paused");
});
