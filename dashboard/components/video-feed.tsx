"use client";
/* eslint-disable @next/next/no-img-element -- MJPEG needs a native, unbuffered image element. */
import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, Radio, RefreshCw } from "lucide-react";
import type { Camera } from "@/lib/types";

export default function VideoFeed({ camera }: { camera: Camera }) {
  const type = camera.feed_type || "clip";
  const video = useRef<HTMLVideoElement>(null);
  const [active, setActive] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [message, setMessage] = useState("Connecting to the video feed…");
  const [error, setError] = useState("");
  const [timestamp, setTimestamp] = useState<string | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [mjpegVersion, setMjpegVersion] = useState(0);
  const lastProgress = useRef(0);
  const progressTime = useRef(-1);
  const base = `/api/cameras/${encodeURIComponent(camera.id)}`;

  useEffect(() => {
    const visibility = () => setActive(!document.hidden);
    document.addEventListener("visibilitychange", visibility);
    const clock = setInterval(() => {
      setTick(Date.now());
      if (type === "hls" && lastProgress.current && Date.now() - lastProgress.current > 20000 && !video.current?.paused) {
        setError("The stream has stopped advancing. Reconnect to check for new video.");
      }
    }, 1000);
    const renew = type === "mjpeg" ? setInterval(() => setMjpegVersion(v => v + 1), 45000) : null;
    return () => { document.removeEventListener("visibilitychange", visibility); clearInterval(clock); if (renew) clearInterval(renew); };
  }, [type]);

  useEffect(() => {
    if (!active || type === "mjpeg") return;
    const mediaElement = video.current;
    if (!mediaElement) return;
    const element: HTMLVideoElement = mediaElement;
    const controller = new AbortController();
    let disposed = false;
    let cleanupHls: (() => void) | undefined;
    let objectUrl: string | null = null;
    let fingerprint: string | null = null;
    let fetching = false;
    const report = (text: string) => { if (!disposed) { setError(text); setMessage(""); } };
    async function clip() {
      if (fetching) return;
      fetching = true;
      try {
        const response = await fetch(base + "/clip", { cache: "no-store", signal: controller.signal });
        if (!response.ok) {
          const body = await response.json();
          throw new Error(body.detail || "The provider clip is unavailable.");
        }
        const blob = await response.blob();
        const bytes = await blob.arrayBuffer();
        const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(n => n.toString(16).padStart(2, "0")).join("");
        if (disposed) return;
        const published = response.headers.get("x-source-timestamp");
        setTimestamp(published && Number.isFinite(Date.parse(published)) ? published : null);
        setError("");
        if (hash === fingerprint) { if (element.ended) setMessage("Clip finished · waiting for the next provider clip"); return; }
        fingerprint = hash;
        const previous = objectUrl;
        objectUrl = URL.createObjectURL(blob);
        element.src = objectUrl;
        element.load();
        if (previous) URL.revokeObjectURL(previous);
        setMessage("");
        await element.play().catch(() => setMessage("Press play to watch the latest clip"));
      } catch (cause) {
        if (!controller.signal.aborted) { element.pause(); element.removeAttribute("src"); element.load(); fingerprint = null; report(cause instanceof Error ? cause.message : "Video unavailable."); }
      } finally { fetching = false; }
    }
    async function connect() {
      setError(""); setMessage("Connecting to the video feed…");
      lastProgress.current = 0; progressTime.current = -1;
      if (type === "clip") { await clip(); return; }
      const { default: Hls } = await import("hls.js");
      if (disposed) return;
      if (Hls.isSupported()) {
        const hls = new Hls({ enableWorker: false, lowLatencyMode: true, liveSyncDurationCount: 2, liveMaxLatencyDurationCount: 6, maxBufferLength: 20 });
        cleanupHls = () => hls.destroy();
        hls.attachMedia(element);
        hls.loadSource(base + "/hls");
        hls.on(Hls.Events.MANIFEST_PARSED, () => element.play().catch(() => { if (!disposed) setMessage("Press play to watch the live stream"); }));
        hls.on(Hls.Events.ERROR, (_, data) => {
          if (data.fatal) { report("The public live stream is unavailable. Reconnect to try again."); hls.destroy(); }
        });
      } else if (element.canPlayType("application/vnd.apple.mpegurl")) {
        element.src = base + "/hls";
        await element.play().catch(() => { if (!disposed) setMessage("Press play to watch the live stream"); });
      } else report("This browser cannot play HLS video. Try a current version of Chrome, Firefox, Edge, or Safari.");
    }
    void connect().catch(() => report("The video player could not connect. Please retry."));
    const refresh = type === "clip" ? setInterval(() => void clip(), 30000) : null;
    return () => {
      disposed = true; controller.abort(); if (refresh) clearInterval(refresh); cleanupHls?.();
      element.pause(); element.removeAttribute("src"); element.load(); if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [active, attempt, base, type]);

  const age = timestamp && tick ? Math.max(0, Math.round((tick - Date.parse(timestamp)) / 1000)) : null;
  const liveEdge = () => {
    const element = video.current;
    if (element?.seekable.length) element.currentTime = Math.max(0, element.seekable.end(element.seekable.length - 1) - 1);
    void element?.play().catch(() => {});
  };
  return <div className="video-feed" data-feed-type={type}>
    {type === "mjpeg" ? active && <img key={`${attempt}-${mjpegVersion}`} className="mjpeg-video" src={`${base}/mjpeg?v=${attempt}-${mjpegVersion}`} alt={`Live video at ${camera.name}`} onLoad={() => { setMessage(""); setError(""); }} onError={() => { setMessage(""); setError("The public live camera disconnected. Reconnect to try again."); }} /> : <video ref={video} controls playsInline autoPlay muted aria-label={type === "hls" ? "Live public camera video" : "Latest public camera video clip"}
      onPlaying={() => { lastProgress.current = Date.now(); setMessage(""); setError(""); }}
      onTimeUpdate={() => {
        const element = video.current;
        if (!element) return;
        if (element.currentTime !== progressTime.current) { lastProgress.current = Date.now(); progressTime.current = element.currentTime; }
        if (type === "hls" && element.seekable.length) setLatency(Math.max(0, element.seekable.end(element.seekable.length - 1) - element.currentTime));
      }} onEnded={() => { if (type === "clip") setMessage("Clip finished · waiting for the next provider clip"); }} />}
    <div className="video-caption"><span><Radio size={12} />{type === "clip" ? "RECENT PROVIDER CLIP" : `LIVE ${type.toUpperCase()}`}</span><span>{type === "clip" ? age === null ? "Provider timestamp unavailable" : `Provider update ${age}s ago` : latency === null ? "Public video stream" : `${latency.toFixed(1)}s behind stream edge`}</span>{type === "hls" && <button onClick={liveEdge}>Go live</button>}</div>
    {type === "clip" && age !== null && age > 300 && <div className="video-status" role="status">This clip is now over five minutes old. Checking for an updated clip…</div>}
    {!active ? <div className="video-status">Video paused while this tab is hidden</div> : error ? <div className="video-status error" role="alert"><AlertCircle size={17} /><span>{error}</span><button className="button light small" onClick={() => { setError(""); setMessage("Reconnecting…"); setAttempt(v => v + 1); }}><RefreshCw size={14} />Reconnect</button></div> : message && <div className="video-status" role="status">{message.startsWith("Connecting") && <Loader2 size={17} className="spin" />}{message}</div>}
    <p className="video-credit">{camera.attribution || "Public camera source"}{type === "clip" ? " · checks for a new clip every 30 seconds" : " · stream latency depends on the provider"}</p>
  </div>;
}
