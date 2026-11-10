"""On-demand camera previews; frames and detections are published together."""
import base64
import hashlib
import logging
import math
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import cv2
import numpy as np

from . import storage
from .network import download
from .vision import Tracker, detector, occupancy
from .streams import feed_type, check_recent, media_playlist, segments, local_segment, jpeg_frames

log = logging.getLogger("flowstate.live")
FPS = 6
LEASE_SECONDS = 15
MAX_CAMERAS = 2


class PreviewBusy(RuntimeError):
    pass


def configuration(camera):
    return (tuple(camera["gate"]), tuple(camera["roi"]), camera["confidence"])


def source_modified(headers):
    try:
        return parsedate_to_datetime(headers["last-modified"]).astimezone(timezone.utc).isoformat()
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


class PreviewWorker:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, name="live-" + camera_id, daemon=True)
        self.sequence = 0
        self.latest = {
            "camera_id": camera_id, "sequence": 0, "status": "connecting",
            "image": None, "detections": [], "message": "Connecting to the camera…",
        }
        self.published = deque(maxlen=20)
        self.trails = {}
        self.configuration_version = 0

    def status(self, status, message):
        with self.lock:
            self.sequence += 1
            self.latest = {**self.latest, "sequence": self.sequence, "status": status, "message": message}
            if self.latest.get("source_modified"):
                self.latest["source_age_seconds"] = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(self.latest["source_modified"])).total_seconds())

    def read(self, after=-1):
        with self.lock:
            if self.latest["sequence"] <= after:
                return {"sequence": self.latest["sequence"], "unchanged": True}
            # Published frames are immutable; return the same image/geometry/detections.
            return dict(self.latest)

    def publish(self, frame, camera, elapsed, tracker, modified, replay=False, pass_number=1):
        height, width = frame.shape[:2]
        if width > 960:
            frame = cv2.resize(frame, (960, round(height * 960 / width)))
        detections = detector.detect(frame, camera["confidence"], camera["roi"])
        if self.stop.is_set():
            return
        if tracker is not None:
            tracker.update(detections, elapsed)
            active = set(tracker.tracks)
            self.trails = {key: value for key, value in self.trails.items() if key in active}
            for detection in detections:
                track_id = detection["track_id"]
                box = detection["box"]
                trail = self.trails.setdefault(track_id, deque(maxlen=8))
                trail.append([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
                detection["trail"] = list(trail)
                detection["counted"] = tracker.tracks[track_id]["counted"]
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if not ok:
            raise ValueError("This camera frame could not be displayed.")
        now = time.monotonic()
        self.published.append(now)
        actual_fps = (len(self.published) - 1) / (now - self.published[0]) if len(self.published) > 1 and now > self.published[0] else 0
        age = None
        if modified:
            age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(modified)).total_seconds())
        payload = {
            "camera_id": self.camera_id, "status": "playing", "message": "",
            "image": "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii"),
            "width": frame.shape[1], "height": frame.shape[0], "detections": detections,
            "gate": list(camera["gate"]), "roi": list(camera["roi"]),
            "confidence": camera["confidence"], "configuration_version": self.configuration_version,
            "source_kind": camera["kind"], "source_modified": modified, "source_age_seconds": age,
            "updated_at": storage.now(), "elapsed": round(elapsed, 3),
            "fps": round(actual_fps, 1), "visible": len(detections),
            "occupancy": round(occupancy(detections, camera["roi"]), 2),
            "crossings": tracker.total if tracker is not None else None,
            "direction": dict(tracker.direction) if tracker is not None else None,
            "replay": replay, "pass_number": pass_number,
        }
        with self.lock:
            self.sequence += 1
            self.latest = {**payload, "sequence": self.sequence}

    def snapshots(self):
        previous = None
        previous_config = None
        while not self.stop.is_set():
            started = time.monotonic()
            camera = storage.get_camera(self.camera_id)
            if not camera:
                raise ValueError("This camera is no longer available.")
            from .providers import snapshot_url
            media, headers = download(snapshot_url(camera), limit=15_000_000, timeout=20)
            if self.stop.is_set():
                return
            fingerprint = hashlib.sha256(media).digest()
            current_config = configuration(camera)
            if fingerprint != previous or current_config != previous_config:
                frame = cv2.imdecode(np.frombuffer(media, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise ValueError("The camera did not return a decodable image.")
                if current_config != previous_config:
                    self.configuration_version += 1
                self.publish(frame, camera, 0, None, source_modified(headers))
                previous, previous_config = fingerprint, current_config
            else:
                self.status("waiting", "The provider image is unchanged. Checking again…")
            self.stop.wait(max(0, 3 - (time.monotonic() - started)))

    def video(self):
        capture = None
        path = None
        fingerprint = None
        last_fetch = -math.inf
        modified = None
        pass_number = 0
        replay = False
        try:
            while not self.stop.is_set():
                camera = storage.get_camera(self.camera_id)
                if not camera or not camera.get("stream_url"):
                    raise ValueError("This camera does not provide a downloadable video clip.")
                if capture is None or time.monotonic() - last_fetch >= 30:
                    self.status("connecting" if capture is None else "refreshing", "Fetching the provider's latest clip…")
                    media, headers = download(camera["stream_url"], limit=80_000_000, timeout=25)
                    check_recent(headers)
                    if self.stop.is_set():
                        return
                    latest_fingerprint = hashlib.sha256(media).digest()
                    last_fetch = time.monotonic()
                    if latest_fingerprint != fingerprint:
                        if capture is not None:
                            capture.release()
                        if path is not None:
                            path.unlink(missing_ok=True)
                        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as file:
                            file.write(media)
                            path = Path(file.name)
                        capture = cv2.VideoCapture(str(path))
                        if not capture.isOpened():
                            raise ValueError("The source must return a downloadable MP4 clip.")
                        fingerprint = latest_fingerprint
                        modified = source_modified(headers)
                        pass_number = 0
                    if pass_number > 0:
                        self.status("waiting", "This clip has finished. Waiting for the provider to publish a new clip…")
                        self.stop.wait(2)
                        continue
                else:
                    self.status("waiting", "This clip has finished. Waiting for the provider to publish a new clip…")
                    self.stop.wait(min(2, max(0, 30 - (time.monotonic() - last_fetch))))
                    continue
                fps = capture.get(cv2.CAP_PROP_FPS)
                total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                if not math.isfinite(fps) or fps <= 0 or not math.isfinite(total) or total <= 0:
                    raise ValueError("The camera clip has no reliable video timestamps.")
                limit = min(int(total), int(fps * 60))
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                pass_number += 1
                tracker = Tracker(camera["gate"])
                self.trails.clear()
                self.published.clear()
                current_config = configuration(camera)
                self.configuration_version += 1
                started = time.monotonic()
                index = 0
                step = max(1, round(fps / FPS))
                last_config_read = started
                decoded = False
                while index < limit and not self.stop.is_set():
                    elapsed = index / fps
                    if self.stop.wait(max(0, started + elapsed - time.monotonic())):
                        return
                    if time.monotonic() - last_config_read >= 0.5:
                        updated = storage.get_camera(self.camera_id)
                        if updated is not None:
                            camera = updated
                        last_config_read = time.monotonic()
                        if configuration(camera) != current_config:
                            current_config = configuration(camera)
                            tracker = Tracker(camera["gate"])
                            self.trails.clear()
                            self.configuration_version += 1
                    ok, frame = capture.read()
                    if not ok:
                        break
                    decoded = True
                    self.publish(frame, camera, elapsed, tracker, modified, replay, pass_number)
                    # Keep playback near source time if inference is slower than the target.
                    target = max(index + step, int((time.monotonic() - started) * fps))
                    index += 1
                    while index < min(target, limit):
                        if self.stop.is_set() or not capture.grab():
                            break
                        index += 1
                if not decoded:
                    raise ValueError("No camera video frames could be decoded.")
                # Finish the last sampled frame's interval before the next pass.
                self.stop.wait(max(0, started + limit / fps - time.monotonic()))
        finally:
            if capture is not None:
                capture.release()
            if path is not None:
                path.unlink(missing_ok=True)

    def mjpeg(self):
        self.trails.clear()
        self.published.clear()
        camera = storage.get_camera(self.camera_id)
        tracker = Tracker(camera["gate"])
        current_config = configuration(camera)
        self.configuration_version += 1
        started = time.monotonic()
        sampled_at = -1
        for media in jpeg_frames(camera["stream_url"], self.stop.is_set, duration=3600):
            elapsed = time.monotonic() - started
            if elapsed - sampled_at < 1 / FPS:
                continue
            sampled_at = elapsed
            camera = storage.get_camera(self.camera_id)
            if configuration(camera) != current_config:
                current_config = configuration(camera)
                tracker = Tracker(camera["gate"])
                self.trails.clear()
                self.configuration_version += 1
            frame = cv2.imdecode(np.frombuffer(media, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                self.publish(frame, camera, elapsed, tracker, None)

    def hls(self):
        self.trails.clear()
        self.published.clear()
        camera = storage.get_camera(self.camera_id)
        tracker = Tracker(camera["gate"])
        current_config = configuration(camera)
        self.configuration_version += 1
        last = None
        timeline = 0
        advanced = time.monotonic()
        while not self.stop.is_set():
            camera = storage.get_camera(self.camera_id)
            text, base, _ = media_playlist(camera)
            if "#EXT-X-ENDLIST" in text:
                raise ValueError("This HLS recording has ended.")
            rows = segments(text, base)
            if last is None:
                last = rows[-1]["sequence"] - 1
            if rows[0]["sequence"] > last + 1 or rows[-1]["sequence"] < last or rows[-1]["sequence"] - last > 3:
                last = rows[-1]["sequence"] - 1
                tracker = Tracker(camera["gate"])
                self.trails.clear()
                self.configuration_version += 1
            new = [row for row in rows if row["sequence"] > last]
            if not new:
                self.status("waiting", "Waiting for the next live video segment…")
                if time.monotonic() - advanced > 30:
                    raise ValueError("The live stream stopped publishing video.")
                self.stop.wait(1)
                continue
            for row in new:
                if self.stop.is_set():
                    return
                if row["discontinuity"]:
                    tracker = Tracker(camera["gate"])
                    self.trails.clear()
                    self.configuration_version += 1
                with local_segment(row) as (path, headers):
                    capture = cv2.VideoCapture(str(path))
                    try:
                        fps = capture.get(cv2.CAP_PROP_FPS)
                        if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
                            raise ValueError("The live segment could not be decoded.")
                        index = 0
                        decoded = False
                        limit = math.ceil(fps * row["duration"])
                        started = time.monotonic()
                        while index < limit and not self.stop.is_set():
                            elapsed = index / fps
                            if self.stop.wait(max(0, started + elapsed - time.monotonic())):
                                return
                            ok, frame = capture.read()
                            if not ok:
                                break
                            camera = storage.get_camera(self.camera_id)
                            if configuration(camera) != current_config:
                                current_config = configuration(camera)
                                tracker = Tracker(camera["gate"])
                                self.trails.clear()
                                self.configuration_version += 1
                            stamp = (row["stamp"] + timedelta(seconds=elapsed)).isoformat() if row["stamp"] else source_modified(headers)
                            self.publish(frame, camera, timeline + elapsed, tracker, stamp)
                            decoded = True
                            target = max(index + max(1, round(fps / FPS)), int((time.monotonic() - started) * fps))
                            index += 1
                            while index < min(target, limit):
                                if self.stop.is_set() or not capture.grab():
                                    break
                                index += 1
                        if not decoded:
                            raise ValueError("The live camera segment contained no video frames.")
                    finally:
                        capture.release()
                timeline += row["duration"]
                last = row["sequence"]
                advanced = time.monotonic()

    def run(self):
        while not self.stop.is_set():
            try:
                camera = storage.get_camera(self.camera_id)
                if not camera:
                    raise ValueError("This camera is no longer available.")
                if feed_type(camera) == "hls":
                    self.hls()
                elif feed_type(camera) == "mjpeg":
                    self.mjpeg()
                elif camera["kind"] == "video":
                    self.video()
                else:
                    self.snapshots()
            except Exception:
                if not self.stop.is_set():
                    log.exception("Live camera preview failed for %s", self.camera_id)
                    self.status("error", "The camera feed is unavailable. Retrying in a few seconds…")
                    self.stop.wait(5)


class LiveManager:
    def __init__(self, maximum=MAX_CAMERAS, clock=time.monotonic):
        self.maximum = maximum
        self.clock = clock
        self.lock = threading.Lock()
        self.workers = {}
        self.sessions = {}
        self.stop = threading.Event()
        self.reaper = None

    def start(self):
        self.reaper = threading.Thread(target=self.reap, name="live-preview-cleanup", daemon=True)
        self.reaper.start()

    def prune_locked(self):
        now = self.clock()
        self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
        watched = {value[0] for value in self.sessions.values()}
        for camera_id, worker in list(self.workers.items()):
            if camera_id not in watched:
                worker.stop.set()
            if not worker.thread.is_alive():
                self.workers.pop(camera_id)

    def create(self, camera_id):
        with self.lock:
            self.prune_locked()
            if len(self.sessions) >= 20:
                raise PreviewBusy("Too many preview viewers. Close another live view and retry.")
            worker = self.workers.get(camera_id)
            if worker is not None and worker.stop.is_set():
                raise PreviewBusy("The previous preview is stopping. Retry in a moment.")
            if worker is None:
                if len(self.workers) >= self.maximum:
                    raise PreviewBusy("Two cameras are already being previewed. Pause another live view and retry.")
                worker = PreviewWorker(camera_id)
                self.workers[camera_id] = worker
            session_id = str(uuid.uuid4())
            self.sessions[session_id] = (camera_id, self.clock() + LEASE_SECONDS)
            if not worker.thread.is_alive():
                worker.thread.start()
            return {"session_id": session_id, "camera_id": camera_id, "lease_seconds": LEASE_SECONDS, "target_fps": FPS}

    def frame(self, session_id, after=-1):
        with self.lock:
            self.prune_locked()
            session = self.sessions.get(session_id)
            if session is None:
                raise LookupError("The live preview expired. Resume the feed to reconnect.")
            camera_id = session[0]
            self.sessions[session_id] = (camera_id, self.clock() + LEASE_SECONDS)
            worker = self.workers.get(camera_id)
            if worker is None:
                raise LookupError("The live preview ended. Resume the feed to reconnect.")
            return worker.read(after)

    def release(self, session_id):
        with self.lock:
            self.sessions.pop(session_id, None)
            self.prune_locked()

    def reap(self):
        while not self.stop.wait(1):
            with self.lock:
                self.prune_locked()

    def close(self):
        self.stop.set()
        with self.lock:
            self.sessions.clear()
            workers = list(self.workers.values())
            for worker in workers:
                worker.stop.set()
        if self.reaper:
            self.reaper.join(timeout=2)
        for worker in workers:
            worker.thread.join(timeout=1)


live = LiveManager()
