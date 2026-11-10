"use client";
import { FormEvent, ReactNode, useEffect, useId, useRef, useState } from "react";
import { X, Plus, CalendarClock, AlertCircle } from "lucide-react";
import { api, write } from "@/lib/api";
import type { Camera } from "@/lib/types";

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement;
    element?.showModal();
    return () => {
      element?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({ preventScroll: true });
    };
  }, []);
  return <dialog ref={dialog} className="modal" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }} onClick={e => { if (e.target === dialog.current) onClose(); }}><div className="modal-inner"><div className="modal-heading"><h2 id={titleId}>{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20} /></button></div>{children}</div></dialog>;
}

export function AddCameraDialog({ onClose, onAdded }: { onClose: () => void; onAdded: (c: Camera) => void }) {
  const [kind, setKind] = useState("snapshot");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault(); setBusy(true); setError("");
    const form = new FormData(e.currentTarget);
    try {
      const camera = await api<Camera>("/cameras", write("POST", { name: form.get("name"), city: form.get("city"), country: form.get("country"), lat: Number(form.get("lat")), lon: Number(form.get("lon")), timezone: form.get("timezone"), source_url: form.get("source_url"), stream_url: kind !== "snapshot" ? form.get("stream_url") : null, kind: kind === "snapshot" ? "snapshot" : "video", feed_type: kind }));
      onAdded(camera); onClose();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <Modal title="Add a public camera" onClose={onClose}><p className="modal-intro">Connect a traffic camera anywhere in the world using its direct image or video URL.</p><form onSubmit={submit} className="form-grid"><label className="full">Camera name<input name="name" required minLength={2} maxLength={120} placeholder="e.g. Main Street / Queen Street" autoFocus /></label><label>City<input name="city" placeholder="Toronto" maxLength={100} /></label><label>Country<input name="country" required minLength={2} placeholder="Canada" maxLength={100} /></label><label>Latitude<input name="lat" required type="number" min="-90" max="90" step="any" placeholder="43.6532" /></label><label>Longitude<input name="lon" required type="number" min="-180" max="180" step="any" placeholder="-79.3832" /></label><label className="full">Camera timezone<input name="timezone" required defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone} placeholder="America/Toronto" /><small>Use an IANA timezone for local scheduling.</small></label><label className="full">Feed type<select value={kind} onChange={e => setKind(e.target.value)}><option value="snapshot">Snapshot · visible vehicle counts</option><option value="hls">Live HLS video (.m3u8)</option><option value="mjpeg">Live MJPEG video</option><option value="clip">Recent MP4 clip</option></select></label><label className="full">Direct image URL<input name="source_url" required type="url" placeholder="https://camera-provider.example/camera.jpg" maxLength={2048} /><small>A publicly accessible JPEG or PNG, without a login.</small></label>{kind !== "snapshot" && <label className="full">Direct video URL<input name="stream_url" required type="url" placeholder="https://camera-provider.example/camera.mp4" maxLength={2048} /><small>A public HLS playlist, continuous MJPEG stream, or recently updated MP4 clip (up to 80 MB). Choose the matching feed type above.</small></label>}{error && <div className="form-error full" role="alert"><AlertCircle size={16} /> {error}</div>}<div className="modal-actions full"><button type="button" className="button light" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}><Plus size={16} /> {busy ? "Connecting…" : "Add camera"}</button></div></form></Modal>;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export function ScheduleDialog({ cameras, initial, onClose, onAdded }: { cameras: Camera[]; initial: Camera | null; onClose: () => void; onAdded: () => void }) {
  const [cameraId, setCameraId] = useState(initial?.id || cameras[0]?.id || "");
  const camera = cameras.find(c => c.id === cameraId);
  const [days, setDays] = useState([0, 1, 2, 3, 4]);
  const [zone, setZone] = useState(camera?.timezone || "UTC");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<string>(camera?.kind || "snapshot");
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault(); setBusy(true); setError(""); const form = new FormData(e.currentTarget);
    try { await api("/schedules", write("POST", { camera_id: cameraId, name: form.get("name"), time: form.get("time"), timezone: zone, days, enabled: true, options: { mode, duration: Number(form.get("duration")), interval: Number(form.get("interval") || 5) } })); onAdded(); onClose(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <Modal title="Schedule a traffic analysis" onClose={onClose}><p className="modal-intro">Measure the same camera at the same time, and build a picture of how traffic changes.</p><form className="form-grid" onSubmit={submit}><label className="full">Schedule name<input name="name" defaultValue="Morning rush hour" maxLength={100} required autoFocus /></label><label className="full">Camera<select value={cameraId} onChange={e => { setCameraId(e.target.value); const c = cameras.find(c => c.id === e.target.value); setZone(c?.timezone || "UTC"); setMode(c?.kind || "snapshot"); }}>{cameras.map(c => <option key={c.id} value={c.id}>{c.name} · {c.city}</option>)}</select></label><label>Time of day<input name="time" required type="time" defaultValue="08:00" /></label><label>Timezone<input required value={zone} onChange={e => setZone(e.target.value)} /></label><fieldset className="full"><legend>Repeat on</legend><div className="weekday-picker">{WEEKDAYS.map((day, i) => <button type="button" key={day} aria-pressed={days.includes(i)} className={days.includes(i) ? "chosen" : ""} onClick={() => setDays(days.includes(i) ? days.filter(d => d !== i) : [...days, i])}>{day}</button>)}</div></fieldset><label>Analysis mode<select value={mode} onChange={e => setMode(e.target.value)}>{camera?.kind === "video" && <option value="video">Video flow</option>}<option value="snapshot">Snapshot counts</option></select></label><label>Observation duration<select name="duration" defaultValue="30"><option value="15">15 seconds</option><option value="30">30 seconds</option><option value="60">1 minute</option><option value="120">2 minutes</option><option value="300">5 minutes</option></select></label>{mode === "snapshot" && <label className="full">Snapshot interval<select name="interval" defaultValue="10"><option value="5">Every 5 seconds</option><option value="10">Every 10 seconds</option><option value="30">Every 30 seconds</option><option value="60">Every minute</option></select></label>}<div className="info-note full"><CalendarClock size={18} /><span>Runs continue while the dashboard is closed. Keep the analysis service running. Short clips are analyzed for their available length.</span></div>{error && <div role="alert" className="form-error full"><AlertCircle size={16} />{error}</div>}<div className="modal-actions full"><button type="button" className="button light" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy || !days.length || !cameraId}><CalendarClock size={16} />{busy ? "Saving…" : "Create schedule"}</button></div></form></Modal>;
}
