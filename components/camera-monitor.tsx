"use client";
import { useEffect, useRef, useState } from "react";
import { Camera as CameraIcon, Crosshair, Eye, Film, RefreshCw, Save, Settings2, X, Maximize2, MapPin } from "lucide-react";
import type { Camera, Run } from "@/lib/types";
import { api, write } from "@/lib/api";

export default function CameraMonitor({ camera, run, onUpdate, onError }: { camera: Camera; run: Run | null; onUpdate: () => void; onError: (s: string) => void }) {
  const [view, setView] = useState<"image" | "detection" | "clip">("image");
  const [refresh, setRefresh] = useState(Date.now());
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<"line" | "roi" | null>(null);
  const [points, setPoints] = useState<number[][]>([]);
  const [gate, setGate] = useState(camera.gate);
  const [roi, setRoi] = useState(camera.roi);
  const [confidence, setConfidence] = useState(camera.confidence);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const stage = useRef<HTMLDivElement>(null);

  useEffect(() => { setGate(camera.gate); setRoi(camera.roi); setConfidence(camera.confidence); setEditing(null); setPoints([]); setFailed(false); setLoaded(false); setRefresh(Date.now()); setView(run?.frame_url ? "detection" : "image"); }, [camera.id]);
  useEffect(() => { setFailed(false); setLoaded(false); }, [view, refresh, run?.id]);
  const source = view === "detection" && run?.frame_url ? run.frame_url + "?v=" + run.progress : `/api/cameras/${camera.id}/snapshot?t=${refresh}`;
  const detections = view === "detection" && run?.frame_url ? run.detections || [] : [];
  const displayGate = view === "detection" && !config ? run?.options.configuration?.gate || gate : gate;
  const displayRoi = view === "detection" && !config ? run?.options.configuration?.roi || roi : roi;
  const handlePoint = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!editing || !loaded) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const point = [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
    if (points.length === 0) setPoints([point]);
    else {
      if (editing === "line") setGate([...points[0], ...point]);
      else setRoi([Math.min(points[0][0], point[0]), Math.min(points[0][1], point[1]), Math.max(points[0][0], point[0]), Math.max(points[0][1], point[1])]);
      setPoints([]); setEditing(null);
    }
  };
  const save = async () => {
    setSaving(true);
    try { await api(`/cameras/${camera.id}`, write("PATCH", { gate, roi, confidence })); onUpdate(); setConfig(false); }
    catch (e) { onError((e as Error).message); }
    finally { setSaving(false); }
  };
  return <section className="panel monitor-panel">
    <div className="panel-title"><div><div className="eyebrow"><CameraIcon size={14} /> CAMERA MONITOR</div><h2>{camera.name}</h2><p className="location"><MapPin size={13} /> {camera.city}, {camera.country} <span>·</span> {new Intl.DateTimeFormat("en", { timeZone: camera.timezone, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date())} local</p></div><button className={config ? "icon-button selected" : "icon-button"} onClick={() => setConfig(!config)} aria-label="Configure camera analysis" title="Configure camera analysis"><Settings2 size={18} /></button></div>
    <div className="monitor-toolbar"><div className="segmented"><button className={view === "image" ? "active" : ""} onClick={() => setView("image")}><CameraIcon size={14} /> Camera image</button><button className={view === "detection" ? "active" : ""} disabled={!run?.frame_url} onClick={() => setView("detection")}><Crosshair size={14} /> Detection view</button>{camera.kind === "video" && <button className={view === "clip" ? "active" : ""} onClick={() => setView("clip")}><Film size={14} /> Clip</button>}</div><div className="inline"><button className="icon-button small" title="Refresh camera image" aria-label="Refresh camera image" onClick={() => { setRefresh(Date.now()); setView("image"); }}><RefreshCw size={15} /></button><button className="icon-button small" aria-label="View camera fullscreen" title="View camera fullscreen" onClick={() => stage.current?.requestFullscreen().catch(() => onError("Fullscreen is unavailable in this browser."))}><Maximize2 size={15} /></button></div></div>
    <div className="monitor-stage" ref={stage}>
      {view === "clip" ? <video key={camera.id} src={`/api/cameras/${camera.id}/clip`} controls playsInline autoPlay muted onError={() => setFailed(true)} aria-label="Latest public camera video clip" /> : <div className={editing ? "frame-container editing" : "frame-container"} onClick={handlePoint}>
        {!failed && <img src={source} alt={`Traffic at ${camera.name}`} onLoad={() => { setLoaded(true); setFailed(false); }} onError={() => setFailed(true)} />}
        {!loaded && !failed && <div className="frame-loading"><RefreshCw size={22} className="spin" /><span>Connecting to camera…</span></div>}
        {loaded && !failed && <svg className="detection-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-label="Vehicle detections and counting line">
          {displayRoi.some((v, i) => v !== [0, 0, 1, 1][i]) && <rect x={displayRoi[0] * 1000} y={displayRoi[1] * 1000} width={(displayRoi[2] - displayRoi[0]) * 1000} height={(displayRoi[3] - displayRoi[1]) * 1000} fill="#b7ef5b" fillOpacity={0.06} stroke="#b7ef5b" strokeWidth={2} strokeDasharray="8 8" />}
          {(view === "detection" || config) && <><line x1={displayGate[0] * 1000} y1={displayGate[1] * 1000} x2={displayGate[2] * 1000} y2={displayGate[3] * 1000} stroke="#b7ef5b" strokeWidth={4} strokeDasharray="12 7" /><circle cx={displayGate[0] * 1000} cy={displayGate[1] * 1000} r={7} fill="#b7ef5b" /><circle cx={displayGate[2] * 1000} cy={displayGate[3] * 1000} r={7} fill="#b7ef5b" /></>}
          {detections.map((d, i) => <g key={i}><rect x={d.box[0] * 1000} y={d.box[1] * 1000} width={(d.box[2] - d.box[0]) * 1000} height={(d.box[3] - d.box[1]) * 1000} fill="none" stroke={d.class === "car" ? "#b7ef5b" : "#80d6ff"} strokeWidth={3} /><text x={d.box[0] * 1000 + 3} y={Math.max(25, d.box[1] * 1000 - 8)} fill="#d9ffa3" fontSize={22} fontWeight={650} stroke="#14221f" strokeWidth={2} paintOrder="stroke">{d.class}{d.track_id ? ` #${d.track_id}` : ""} · {Math.round(d.confidence * 100)}%</text></g>)}
          {points.map((p, i) => <circle key={i} cx={p[0] * 1000} cy={p[1] * 1000} r={9} fill="#fff" />)}
        </svg>}
        {loaded && !failed && <div className="frame-label"><span className="feed-label">{view === "detection" ? "ANALYZED FRAME" : "PROVIDER SNAPSHOT"}</span><span>{view === "detection" ? `${detections.length} vehicles visible` : camera.provider === "tfl" ? "© Transport for London" : camera.provider === "digitraffic" ? "© Fintraffic · CC BY 4.0" : "Public camera source"}</span></div>}
      </div>}
      {failed && <div className="frame-error"><CameraIcon size={30} /><strong>Camera image unavailable</strong><p>The provider may be offline or updating the feed.</p><button className="button light" onClick={() => { setFailed(false); setLoaded(false); setRefresh(Date.now()); setView("image"); }}><RefreshCw size={15} /> Retry camera</button></div>}
    </div>
    {config && <div className="camera-config"><div className="config-heading"><strong>Analysis area & counting line</strong><button className="icon-button small" aria-label="Close camera configuration" onClick={() => { setConfig(false); setEditing(null); }}><X size={16} /></button></div><p>{editing ? points.length ? "Click the second point to finish." : editing === "line" ? "Click two points across the road to place the counting line." : "Click two opposite corners to select the analysis area." : "Place a line across the road. Vehicles are counted once when their centers cross it."}</p><div className="config-controls"><button className="button light small" onClick={() => { setView("image"); setEditing("line"); setPoints([]); }}><Crosshair size={15} /> Draw line</button><button className="button light small" onClick={() => { setView("image"); setEditing("roi"); setPoints([]); }}><Maximize2 size={15} /> Select area</button><button className="text-button" onClick={() => { setGate([0.15, 0.6, 0.85, 0.6]); setRoi([0, 0, 1, 1]); }}>Reset</button><label className="confidence-control">Confidence <input type="range" min="0.1" max="0.9" step="0.05" value={confidence} onChange={e => setConfidence(Number(e.target.value))} /><span>{Math.round(confidence * 100)}%</span></label><button className="button primary small" disabled={saving || !!editing} onClick={save}><Save size={15} /> {saving ? "Saving…" : "Save"}</button></div></div>}
    <div className="monitor-footer"><span><Eye size={14} /> {view === "detection" && run ? `Captured during analysis · ${new Date(run.created_at).toLocaleString()}` : "Images refresh on request"}</span><span>{camera.kind === "video" ? "Video + snapshots" : "Snapshots only"}</span></div>
  </section>;
}
