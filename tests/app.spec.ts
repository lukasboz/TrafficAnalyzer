import { test, expect } from "@playwright/test";

test("public camera directory and analysis monitor", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Traffic overview." })).toBeVisible();
  await expect(page.locator(".frame-container img")).toBeVisible();
  await expect.poll(() => page.locator(".frame-container img").evaluate((e: HTMLImageElement) => e.naturalWidth)).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Search cameras").fill("Inkoo");
  await expect(page.locator(".camera-list-item")).toHaveCount(1);
  await page.locator(".camera-item-main").click();
  await page.getByRole("button", { name: "Open monitor" }).click();
  await expect(page.getByLabel("Analysis mode")).toHaveValue("snapshot");
  await page.getByLabel("Observation duration").selectOption("0");
  await page.getByRole("button", { name: "Run analysis", exact: true }).click();
  await expect(page.getByRole("button", { name: "Run analysis", exact: true })).toBeVisible({ timeout: 45000 });
  await expect(page.getByRole("button", { name: "Detection view" })).toBeEnabled({ timeout: 45000 });
  await page.getByRole("button", { name: "Detection view" }).click();
  await expect(page.getByText("ANALYZED FRAME", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../.runtime/desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("schedule creation, persistence, pause and deletion", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await page.getByRole("button", { name: "Schedules", exact: true }).click();
  await page.getByRole("button", { name: "Create schedule", exact: true }).click();
  await page.getByLabel("Schedule name").fill("Browser validation schedule");
  await page.getByLabel("Time of day").fill("23:59");
  await page.getByRole("dialog").getByRole("button", { name: "Create schedule" }).click();
  await expect(page.getByRole("heading", { name: "Browser validation schedule" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await page.getByRole("button", { name: "Schedules", exact: true }).click();
  const card = page.locator(".schedule-card").filter({ hasText: "Browser validation schedule" });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(card.getByText("Paused", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Delete Browser validation schedule" }).click();
  await expect(card).toHaveCount(0);
});

test("report chart and CSV export", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  await page.getByRole("button", { name: "Traffic reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Traffic by time of day" })).toBeVisible();
  const result = await page.request.get("/api/export.csv");
  expect(result.status()).toBe(200);
  const text = await result.text();
  expect(text).toContain("flow_vehicles_per_second");
  expect(text).toContain("image_occupancy_percent");
});

test("mobile layout and camera form validation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Analysis service online" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await expect(page.getByLabel("Search cameras")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("button", { name: "Add camera", exact: true }).click();
  await page.getByLabel("Camera name").fill("Blocked private feed");
  await page.getByLabel("Country", { exact: true }).fill("Canada");
  await page.getByLabel("Latitude", { exact: true }).fill("43.65");
  await page.getByLabel("Longitude", { exact: true }).fill("-79.38");
  await page.getByLabel("Direct image URL").fill("http://127.0.0.1/camera.jpg");
  await page.getByRole("dialog").getByRole("button", { name: "Add camera" }).click();
  await expect(page.getByRole("alert")).toContainText("publicly reachable");
  await expect(page.getByLabel("Camera name")).toHaveValue("Blocked private feed");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.screenshot({ path: "../.runtime/mobile.png", fullPage: true });
});
