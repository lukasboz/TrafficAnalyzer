import { test, expect } from "@playwright/test";
import type { Camera } from "../lib/types";

test("real HLS playback advances at the live edge and explorer defaults to video", async ({ page }) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  const video = page.getByLabel("Live public camera video");
  await expect(page.getByRole("heading", { name: "Hwy 5 at Pocket", exact: true })).toBeVisible();
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime), { timeout: 40000 }).toBeGreaterThan(0);
  const started = await video.evaluate((element: HTMLVideoElement) => ({ time: element.currentTime, edge: element.seekable.end(element.seekable.length - 1) }));
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime), { timeout: 15000 }).toBeGreaterThan(started.time + 2);
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.seekable.length ? element.seekable.end(element.seekable.length - 1) : 0), { timeout: 40000 }).toBeGreaterThan(started.edge + 3);
  await expect(page.locator(".video-caption")).toContainText("LIVE HLS");
  await page.getByRole("button", { name: "Go live", exact: true }).click();
  await expect(page.locator(".video-status.error")).toHaveCount(0);
  await page.screenshot({ path: "../.runtime/live-hls.png", fullPage: true });
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await expect(page.getByLabel("Filter by feed type")).toHaveValue("video");
  await expect(page.locator(".camera-list")).not.toContainText("Snapshot counts");
  await page.getByLabel("Filter by feed type").selectOption("live");
  await page.getByLabel("Filter by country or territory").selectOption("Norway");
  await expect(page.locator(".camera-list-item").first()).toContainText("Live HLS video");
  await page.getByLabel("Filter by country or territory").selectOption("Taiwan");
  await expect(page.locator(".camera-list-item").first()).toContainText("Live MJPEG video");
  expect(errors).toEqual([]);
});

test("Taiwan MJPEG plays continuous changing frames on mobile", async ({ page }) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width: 390, height: 844 });
  const response = await page.request.get("/api/cameras?provider=taiwan&search=CCTV-14-0620-009-002");
  const camera = (await response.json()).items[0] as Camera;
  expect(camera.feed_type).toBe("mjpeg");
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Filter by network").selectOption("taiwan");
  await page.getByLabel("Search cameras").fill(camera.name);
  await page.locator(".camera-item-main").first().click();
  await page.getByRole("button", { name: "Open monitor", exact: true }).click();
  const image = page.locator(".mjpeg-video");
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth), { timeout: 20000 }).toBeGreaterThan(0);
  const frame = await image.screenshot();
  await expect.poll(async () => !(await image.screenshot()).equals(frame), { timeout: 10000 }).toBe(true);
  await expect(page.locator(".video-caption")).toContainText("LIVE MJPEG");
  await expect(page.locator(".video-status.error")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../.runtime/live-mjpeg-mobile.png", fullPage: true });
});

test("recent London clip exposes its timestamp and does not automatically replay", async ({ page }) => {
  test.setTimeout(60000);
  await page.goto("/");
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Filter by feed type").selectOption("clip");
  await page.getByLabel("Search cameras").fill("Marylebone");
  await page.locator(".camera-item-main").first().click();
  await page.getByRole("button", { name: "Open monitor", exact: true }).click();
  const video = page.getByLabel("Latest public camera video clip");
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime), { timeout: 30000 }).toBeGreaterThan(0);
  await expect(page.locator(".video-caption")).toContainText(/Provider update \d+s ago/);
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.ended), { timeout: 20000 }).toBe(true);
  await expect(page.getByRole("status").filter({ hasText: "Clip finished" })).toBeVisible();
  expect(await video.evaluate((element: HTMLVideoElement) => element.loop)).toBe(false);
});
