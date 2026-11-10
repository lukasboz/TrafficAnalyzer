"use client";

import { useCallback } from "react";
import { useSearchParams } from "next/navigation";

export type Section = "overview" | "cameras" | "schedules" | "reports";
type Feed = "video" | "live" | "clip" | "snapshot" | "all";
type ReportMetric = "visible" | "flow" | "occupancy";
type DashboardView = {
  section: Section;
  cameraId: string;
  runId: string;
  search: string;
  feed: Feed;
  network: string;
  country: string;
  saved: boolean;
  reportCamera: string;
  reportDays: number;
  reportMetric: ReportMetric;
};

const defaults: DashboardView = {
  section: "overview", cameraId: "", runId: "", search: "", feed: "video",
  network: "", country: "", saved: false, reportCamera: "", reportDays: 7, reportMetric: "visible",
};
const parameters: Record<keyof DashboardView, string> = {
  section: "view", cameraId: "camera", runId: "run", search: "q", feed: "feed",
  network: "network", country: "country", saved: "saved", reportCamera: "report_camera",
  reportDays: "days", reportMetric: "metric",
};
const choice = <T extends string>(value: string | null, choices: readonly T[], fallback: T): T =>
  choices.includes(value as T) ? value as T : fallback;

export function useDashboardView() {
  const params = useSearchParams();
  const requestedDays = Number(params.get("days"));
  const view: DashboardView = {
    section: choice(params.get("view"), ["overview", "cameras", "schedules", "reports"], defaults.section),
    cameraId: params.get("camera") || "",
    runId: params.get("run") || "",
    search: params.get("q") || "",
    feed: choice(params.get("feed"), ["video", "live", "clip", "snapshot", "all"], defaults.feed),
    network: params.get("network") || "",
    country: params.get("country") || "",
    saved: params.get("saved") === "1",
    reportCamera: params.get("report_camera") || "",
    reportDays: [1, 7, 30, 90, 365].includes(requestedDays) ? requestedDays : defaults.reportDays,
    reportMetric: choice(params.get("metric"), ["visible", "flow", "occupancy"], defaults.reportMetric),
  };

  const updateView = useCallback((patch: Partial<DashboardView>, history: "push" | "replace" = "push") => {
    // Read the current URL so several changes in one event preserve each other.
    const url = new URL(window.location.href);
    for (const key of Object.keys(patch) as (keyof DashboardView)[]) {
      const value = patch[key];
      if (value === undefined) continue;
      if (value === defaults[key]) url.searchParams.delete(parameters[key]);
      else url.searchParams.set(parameters[key], typeof value === "boolean" ? "1" : String(value));
    }
    if (url.href === window.location.href) return;
    window.history[history === "push" ? "pushState" : "replaceState"](null, "", url.pathname + url.search + url.hash);
  }, []);

  return { view, updateView };
}
