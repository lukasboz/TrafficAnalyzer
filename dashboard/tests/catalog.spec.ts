import { test, expect } from "@playwright/test";

test("global catalog loads every API page and filters countries and networks", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const response = await page.request.get("/api/cameras?limit=1");
  const catalog = await response.json() as { total: number };
  expect(catalog.total).toBeGreaterThan(4000);
  await page.goto("/");
  await page.getByRole("button", { name: "Camera explorer", exact: true }).click();
  await page.getByLabel("Filter by feed type").selectOption("all");
  await expect(page.locator(".result-count")).toHaveText(`${catalog.total.toLocaleString()} cameras`);
  await expect(page.locator(".explorer-map canvas")).toBeVisible();
  await expect(page.locator(".explorer-map .leaflet-tile").first()).toHaveAttribute("src", /\/[0-3]\/\d+\/\d+\.png/);
  await expect.poll(() => page.locator(".explorer-map canvas").evaluate((canvas: HTMLCanvasElement) => {
    const pixels = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) return true;
    return false;
  })).toBe(true);
  await page.screenshot({ path: "../.runtime/global-explorer.png", fullPage: true });
  await page.getByLabel("Filter by country or territory").selectOption("Australia");
  await expect(page.locator(".camera-list-item").first()).toContainText("Australia");
  await expect(page.locator(".camera-list")).not.toContainText("Finland");
  await page.getByLabel("Filter by network").selectOption("nsw");
  const network = await (await page.request.get("/api/cameras?provider=nsw&limit=1")).json() as { total: number };
  await expect(page.locator(".result-count")).toHaveText(`${network.total.toLocaleString()} cameras`);
  await page.getByLabel("Filter by country or territory").selectOption("");
  await page.getByLabel("Filter by network").selectOption("saopaulo");
  await expect(page.locator(".camera-list-item").first()).toContainText("Brazil");
  await expect(page.getByText("Map coordinates are not published for these cameras. Choose a camera from the list.")).toBeVisible();
  await page.locator(".camera-item-main").first().click();
  await page.getByRole("button", { name: "Open monitor", exact: true }).click();
  await expect(page.getByText("Map coordinates not published", { exact: true })).toBeVisible();
  await expect.poll(() => page.locator(".frame-container img").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "../.runtime/global-monitor.png", fullPage: true });
});

test("source management exposes global coverage and import status on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Analysis service online" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "CET São Paulo", exact: true })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "NZ Transport Agency Waka Kotahi", exact: true })).toBeVisible();
  await expect(dialog.getByText(/This catalog does not include every public camera/)).toBeVisible();
  await expect(dialog.getByText(/Last imported/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
