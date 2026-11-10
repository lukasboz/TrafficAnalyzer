"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Activity, Car, Crosshair, Pause, Play, RefreshCw, Radio, Clock3, AlertCircle } from "lucide-react";
import { api, write } from "@/lib/api";
import type { Camera, LiveFrame } from "@/lib/types";
import "./live-preview.css";

const subscribeVisibility = (callback: () => void) => {
  document.addEventListener("visibilitychange", callback);
  return () => document.removeEventListener("visibilitychange", callback);
};
const visibleSnapshot = () => document.visibilityState !== "hidden";
const serverVisibility = () => true;

function drawFrame(context: CanvasRenderingContext2D, image: HTMLImageElement, frame: LiveFrame, trails: boolean, labels: boolean, displayWidth: number, pixelRatio: number) {
  const sourceWidth = frame.width || image.naturalWidth;
  const sourceHeight = frame.height || image.naturalHeight;
  const width = displayWidth;
  const height = width * sourceHeight / sourceWidth;
  // Size the bitmap to the screen, not the low-resolution provider image.
  // Draw in CSS pixels so normalized geometry and stroke sizes stay aligned.
  const bitmapWidth = Math.ceil(width * pixelRatio);
  const bitmapHeight = Math.ceil(height * pixelRatio);
  if (context.canvas.width !== bitmapWidth) context.canvas.width = bitmapWidth;
  if (context.canvas.height !== bitmapHeight) context.canvas.height = bitmapHeight;
  context.canvas.style.aspectRatio = `${sourceWidth} / ${sourceHeight}`;
  context.setTransform(bitmapWidth / width, 0, 0, bitmapHeight / height, 0, 0);
  context.clearRect(0, 0, width, height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(image, 0, 0, width, height);
  const gate = frame.gate!;
  const roi = frame.roi!;
  const scale = Math.max(0.85, Math.min(1, width / 640));
  context.lineWidth = 2 * scale;
  if (roi.some((value, index) => value !== [0, 0, 1, 1][index])) {
    const [x1, y1, x2, y2] = [roi[0] * width, roi[1] * height, roi[2] * width, roi[3] * height];
    context.fillStyle = "#071a1780";
    context.fillRect(0, 0, width, y1); context.fillRect(0, y2, width, height - y2);
    context.fillRect(0, y1, x1, y2 - y1); context.fillRect(x2, y1, width - x2, y2 - y1);
    context.strokeStyle = "#b7ef5b"; context.setLineDash([6 * scale, 5 * scale]);
    context.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }
  context.strokeStyle = "#b7ef5b"; context.lineWidth = 2.5 * scale;
  context.setLineDash([10 * scale, 6 * scale]); context.beginPath();
  context.moveTo(gate[0] * width, gate[1] * height); context.lineTo(gate[2] * width, gate[3] * height); context.stroke();
  context.setLineDash([]);
  context.fillStyle = "#b7ef5b";
  for (const offset of [0, 2]) {
    context.beginPath(); context.arc(gate[offset] * width, gate[offset + 1] * height, 4 * scale, 0, Math.PI * 2); context.fill();
  }
  context.font = `600 ${12 * scale}px system-ui, sans-serif`;
  const midX = (gate[0] + gate[2]) * width / 2, midY = (gate[1] + gate[3]) * height / 2;
  const dx = (gate[2] - gate[0]) * width, dy = (gate[3] - gate[1]) * height, length = Math.hypot(dx, dy) || 1;
  context.fillText("A", midX + dy / length * 16 * scale, midY - dx / length * 16 * scale);
  context.fillText("B", midX - dy / length * 16 * scale, midY + dx / length * 23 * scale);
  const placedLabels: { left: number; top: number; width: number; height: number }[] = [];
  const detections = [...frame.detections].sort((a, b) => (a.track_id || a.box[1] * 1000) - (b.track_id || b.box[1] * 1000));
  for (const detection of detections) {
    const [x1, y1, x2, y2] = [detection.box[0] * width, detection.box[1] * height, detection.box[2] * width, detection.box[3] * height];
    const color = detection.counted ? "#76ddc8" : detection.class === "car" ? "#b7ef5b" : "#80d6ff";
    context.strokeStyle = color; context.lineWidth = 1.8 * scale;
    if (trails && detection.trail?.length) {
      context.beginPath();
      detection.trail.forEach((point, index) => { if (index) context.lineTo(point[0] * width, point[1] * height); else context.moveTo(point[0] * width, point[1] * height); });
      context.stroke();
    }
    context.strokeRect(x1, y1, x2 - x1, y2 - y1);
    context.fillStyle = color; context.beginPath(); context.arc((x1 + x2) / 2, (y1 + y2) / 2, 2 * scale, 0, Math.PI * 2); context.fill();
    if (labels) {
      const text = `${detection.class}${detection.track_id ? " #" + detection.track_id : ""} · ${Math.round(detection.confidence * 100)}%`;
      const textWidth = context.measureText(text).width;
      const left = Math.max(0, Math.min(x1, width - textWidth - 8 * scale));
      const labelWidth = textWidth + 8 * scale, labelHeight = 20 * scale;
      let top = Math.max(0, y1 - 22 * scale);
      // Move close labels apart while keeping each connected to its own box.
      for (let attempt = 0; attempt < 10; attempt++) {
        const overlap = placedLabels.some(label => left < label.left + label.width && left + labelWidth > label.left && top < label.top + label.height && top + labelHeight > label.top);
        if (!overlap) break;
        top = Math.max(0, Math.min(height - labelHeight, y1 - (attempt + 2) * (labelHeight + 2 * scale)));
      }
      placedLabels.push({ left, top, width: labelWidth, height: labelHeight });
      if (Math.abs(top - (y1 - 22 * scale)) > 3 * scale) {
        context.beginPath(); context.moveTo(left + labelWidth / 2, top + labelHeight); context.lineTo(x1 + (x2 - x1) / 2, y1); context.stroke();
      }
      context.fillStyle = "#14251fe8"; context.fillRect(left, top, textWidth + 8 * scale, 20 * scale);
      context.fillStyle = color; context.fillText(text, left + 4 * scale, top + 14 * scale);
    }
  }
}

export default function LivePreview({ camera }: { camera: Camera }) {
  const visible = useSyncExternalStore(subscribeVisibility, visibleSnapshot, serverVisibility);
  const [paused, setPaused] = useState(false);
  const [retry, setRetry] = useState(0);
  const [packet, setPacket] = useState<LiveFrame | null>(null);
  const [displayed, setDisplayed] = useState<LiveFrame | null>(null);
  const [error, setError] = useState("");
  const [trails, setTrails] = useState(true);
  const [labels, setLabels] = useState(true);
  const [surface, setSurface] = useState({ width: 0, pixelRatio: 1 });
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const container = canvas.current?.parentElement;
    if (!container) return;
    let densityQuery: MediaQueryList | undefined;
    let observedPixelRatio = window.devicePixelRatio || 1;
    const measure = () => {
      const width = container.getBoundingClientRect().width;
      const pixelRatio = window.devicePixelRatio || 1;
      if (width > 0) setSurface(previous => previous.width === width && previous.pixelRatio === pixelRatio ? previous : { width, pixelRatio });
    };
    const watchDensity = () => {
      densityQuery?.removeEventListener("change", watchDensity);
      observedPixelRatio = window.devicePixelRatio || 1;
      densityQuery = window.matchMedia(`(resolution: ${observedPixelRatio}dppx)`);
      densityQuery.addEventListener("change", watchDensity);
      measure();
    };
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    window.addEventListener("resize", measure);
    watchDensity();
    // Some display-density changes arrive without resize/media-query events.
    // Check independently of frame polling so a paused preview stays sharp.
    const densityCheck = window.setInterval(() => {
      if ((window.devicePixelRatio || 1) !== observedPixelRatio) watchDensity();
    }, 1000);
    return () => {
      observer.disconnect();
      window.clearInterval(densityCheck);
      window.removeEventListener("resize", measure);
      densityQuery?.removeEventListener("change", watchDensity);
    };
  }, []);

  useEffect(() => {
    if (paused || !visible) return;
    let active = true;
    let session = "";
    let released = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const release = () => {
      if (!session || released) return;
      released = true;
      void fetch("/api/live/" + session, { method: "DELETE", keepalive: true }).catch(() => {});
    };
    const wait = (milliseconds: number) => new Promise<void>(resolve => {
      const finish = () => { controller.signal.removeEventListener("abort", finish); if (timer) clearTimeout(timer); resolve(); };
      controller.signal.addEventListener("abort", finish, { once: true });
      timer = setTimeout(finish, milliseconds);
      if (controller.signal.aborted) finish();
    });
    const run = async () => {
      try {
        let started: { session_id: string } | undefined;
        for (let attempt = 0; attempt < 3 && active; attempt++) {
          try { started = await api<{ session_id: string }>(`/cameras/${encodeURIComponent(camera.id)}/live`, { ...write("POST"), signal: controller.signal }); break; }
          catch (error) { if (!active || attempt === 2) throw error; await wait(1500); }
        }
        if (!started) return;
        session = started.session_id;
        if (!active) { release(); return; }
        setError("");
        let sequence = -1;
        while (active) {
          const next = await api<LiveFrame | { unchanged: true; sequence: number }>(`/live/${session}/frame?after=${sequence}`, {
            signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
          });
          if (!active) break;
          if (!("unchanged" in next)) { sequence = next.sequence; setPacket(next); }
          await wait(130);
        }
      } catch (error) {
        if (active) setError((error as Error).message || "The live preview disconnected. Retry to reconnect.");
      } finally { release(); }
    };
    void run();
    return () => { active = false; controller.abort(); if (timer) clearTimeout(timer); release(); };
  }, [camera.id, paused, visible, retry]);

  useEffect(() => {
    if (!packet?.image || !packet.gate || !packet.roi || !surface.width) return;
    let active = true;
    const image = new Image();
    image.src = packet.image;
    void image.decode().then(() => {
      const context = canvas.current?.getContext("2d");
      if (!active || !context) return;
      // Paint the source image, boxes, trails, and counting geometry in one pass.
      drawFrame(context, image, packet, trails, labels, surface.width, surface.pixelRatio);
      setDisplayed(packet);
    }).catch(() => { if (active) setError("This live frame could not be displayed. Retry the feed."); });
    return () => { active = false; };
  }, [packet, trails, labels, surface]);

  const stopped = paused || !visible;
  const status = stopped ? "paused" : error || packet?.status === "error" ? "error" : packet?.status || "connecting";
  const sourceAge = displayed?.source_age_seconds;
  const ageLabel = sourceAge == null ? "Not provided" : sourceAge < 60 ? `${Math.round(sourceAge)} sec` : `${Math.round(sourceAge / 60)} min`;
  return <div className="live-preview" data-testid="live-preview" data-sequence={displayed?.sequence ?? -1} data-status={status}>
    <div className="live-controls">
      <div className="live-status"><span className={status === "playing" ? "live-dot running" : "live-dot"} /><strong>{status === "paused" ? "Detection paused" : status === "error" ? "Feed interrupted" : status === "playing" ? "Detection running" : status === "waiting" ? "Waiting for camera update" : status === "refreshing" ? "Checking for a newer clip" : "Connecting to camera"}</strong></div>
      <div className="live-controls-actions">
        <label><input type="checkbox" checked={trails} onChange={event => setTrails(event.target.checked)} />Trails</label>
        <label><input type="checkbox" checked={labels} onChange={event => setLabels(event.target.checked)} />Labels</label>
        <button className="button light small" onClick={() => setPaused(!paused)}>{paused ? <Play size={14} /> : <Pause size={14} />}{paused ? "Resume feed" : "Pause feed"}</button>
      </div>
    </div>
    {error && <div className="live-alert" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="text-button" onClick={() => { setError(""); setPaused(false); setRetry(value => value + 1); }}>Retry feed</button></div>}
    <div className="live-frame">
      <canvas ref={canvas} aria-label="Live camera feed with vehicle boxes, tracking trails, analysis area, and counting line" style={{ display: displayed ? "block" : "none" }} />
      {!displayed && <div className="live-loading"><RefreshCw className="spin" size={25} /><span>{packet?.message || "Loading camera frames and vehicle detections…"}</span></div>}
      {displayed && <div className="live-frame-label"><span><Radio size={12} />{camera.kind === "snapshot" ? "REFRESHING SNAPSHOTS" : camera.feed_type === "hls" || camera.feed_type === "mjpeg" ? "LIVE VIDEO DETECTION" : displayed.replay ? `CLIP REPLAY · PASS ${displayed.pass_number}` : "LATEST PROVIDER CLIP"}</span><span>{camera.kind === "video" ? displayed.elapsed?.toFixed(1) + "s" : displayed.updated_at ? new Date(displayed.updated_at).toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}{stopped ? " · paused" : ""}</span></div>}
      {packet?.status === "error" && !error && <div className="live-provider-error" role="status">{packet.message}</div>}
    </div>
    <div className="live-metrics">
      <div><span><Car size={14} />Visible now</span><strong>{displayed?.visible ?? "—"} <small>vehicles</small></strong></div>
      <div><span><Crosshair size={14} />{camera.feed_type === "hls" || camera.feed_type === "mjpeg" ? "Crossings this session" : "Crossings this clip"}</span><strong>{displayed?.crossings ?? "—"}<small>{displayed?.direction ? `A → B: ${displayed.direction.a_to_b} · B → A: ${displayed.direction.b_to_a}` : "Video required"}</small></strong></div>
      <div><span><Activity size={14} />{camera.kind === "video" ? "Detection rate" : "Refresh check"}</span><strong>{camera.kind === "video" ? displayed?.fps?.toFixed(1) ?? "—" : "3"} <small>{camera.kind === "video" ? "fps" : "sec"}</small></strong></div>
      <div><span><Clock3 size={14} />Provider age</span><strong className="live-age">{ageLabel}<small>From provider metadata</small></strong></div>
    </div>
    <p className="live-notice">{camera.feed_type === "hls" || camera.feed_type === "mjpeg" ? "Detections follow new live video frames. Crossing counts reset after a stream gap, reconnect, or saved configuration change." : camera.kind === "video" ? "Each new clip plays once with synchronized detections, then waits for a fresh clip. Crossing counts reset with each new clip or saved configuration change." : "Images are checked every 3 seconds. Detections update when the provider image changes. Still images cannot establish passing-vehicle flow."} Preview counts are temporary; use Run analysis to save an observation.</p>
  </div>;
}
