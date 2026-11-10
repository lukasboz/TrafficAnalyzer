export type Metrics = {
  mode: "video" | "snapshot"; visible_mean: number; visible_peak: number; occupancy_mean: number;
  crossings: number | null; flow_per_second: number | null; flow_per_minute: number | null;
  duration: number; frames: number; sampling_fps: number | null; class_counts: Record<string, number>;
  direction: { a_to_b: number; b_to_a: number } | null; confidence_mean: number | null;
  unchanged_samples: number; source_age_seconds: number | null; source_modified: string | null; note: string;
};
export type Camera = {
  id: string; name: string; city: string; country: string; lat: number | null; lon: number | null; timezone: string;
  provider: string; source_url: string; stream_url: string | null; kind: "video" | "snapshot";
  feed_type?: "snapshot" | "clip" | "hls" | "mjpeg";
  saved: boolean; gate: number[]; roi: number[]; confidence: number; attribution?: string;
  latest_metrics?: Metrics | null; last_analyzed?: string | null;
};
export type Detection = { box: number[]; class: string; confidence: number; track_id?: number };
export type LiveDetection = Detection & { trail?: number[][]; counted?: boolean };
export type LiveFrame = {
  camera_id: string; sequence: number; status: "connecting" | "playing" | "waiting" | "refreshing" | "error";
  image: string | null; detections: LiveDetection[]; message: string;
  width?: number; height?: number; gate?: number[]; roi?: number[]; confidence?: number;
  configuration_version?: number; source_kind?: "snapshot" | "video"; source_modified?: string | null;
  source_age_seconds?: number | null; updated_at?: string; elapsed?: number; fps?: number;
  visible?: number; occupancy?: number; crossings?: number | null;
  direction?: { a_to_b: number; b_to_a: number } | null; replay?: boolean; pass_number?: number;
};
export type Sample = { elapsed: number; visible: number; occupancy: number; crossings: number; counts: Record<string, number> };
export type Run = {
  id: string; camera_id: string; camera_name?: string; camera_timezone?: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "skipped";
  created_at: string; finished_at: string | null; progress: number; error: string | null;
  metrics: Metrics | null; frame_url: string | null; detections: Detection[] | null;
  options: { mode: "video" | "snapshot"; duration: number; interval: number; configuration?: { gate: number[]; roi: number[]; confidence: number } }; samples?: Sample[];
};
export type Schedule = {
  id: string; name: string; camera_id: string; camera_name: string; time: string; timezone: string;
  days: number[]; enabled: boolean; next_run: string | null; options: Run["options"];
};
export type Health = { status: string; model: string; model_ready: boolean; model_error?: string; cameras: number; runs: Record<string, number>; scheduler: string; time: string; workers: number; provider_errors: string[] };
export type Provider = { id: string; name: string; region: string; kind: string; url: string; description: string; attribution: string; count: number; last_updated?: string; error?: string | null; refreshing?: boolean };
export type Report = { hourly: { hour: number; runs: number; visible: number | null; occupancy: number | null; flow: number | null }[]; runs: Run[]; limited: boolean };
