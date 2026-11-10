import base64
import threading

import cv2
import numpy as np
import pytest

from backend import live as preview


class FakeThread:
    def __init__(self):
        self.alive = False

    def is_alive(self):
        return self.alive

    def start(self):
        self.alive = True

    def join(self, timeout=None):
        self.alive = False


class FakeWorker:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.thread = FakeThread()
        self.stop = threading.Event()

    def read(self, after):
        return {"camera_id": self.camera_id, "sequence": 1}


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(preview, "PreviewWorker", FakeWorker)
    now = [0]
    instance = preview.LiveManager(clock=lambda: now[0])
    yield instance, now
    instance.close()


def test_viewers_share_camera_worker_and_release_independently(manager):
    instance, _ = manager
    first = instance.create("camera")
    second = instance.create("camera")
    assert len(instance.workers) == 1
    worker = instance.workers["camera"]
    instance.release(first["session_id"])
    assert not worker.stop.is_set()
    assert instance.frame(second["session_id"])["camera_id"] == "camera"
    instance.release(second["session_id"])
    assert worker.stop.is_set()
    with pytest.raises(LookupError):
        instance.frame(second["session_id"])


def test_expired_leases_stop_workers_without_requiring_browser_cleanup(manager):
    instance, now = manager
    session = instance.create("camera")
    now[0] = 16
    with pytest.raises(LookupError):
        instance.frame(session["session_id"])
    assert instance.workers["camera"].stop.is_set()


def test_polling_renews_only_that_viewer_lease(manager):
    instance, now = manager
    first = instance.create("camera")
    second = instance.create("camera")
    now[0] = 10
    instance.frame(first["session_id"])
    now[0] = 16
    assert instance.frame(first["session_id"])["sequence"] == 1
    assert second["session_id"] not in instance.sessions
    assert not instance.workers["camera"].stop.is_set()


def test_worker_capacity_includes_threads_still_stopping(manager):
    instance, _ = manager
    first = instance.create("one")
    instance.create("two")
    instance.release(first["session_id"])
    with pytest.raises(preview.PreviewBusy):
        instance.create("three")
    with pytest.raises(preview.PreviewBusy):
        instance.create("one")
    instance.workers["one"].thread.alive = False
    assert instance.create("three")["camera_id"] == "three"


def test_preview_frame_keeps_geometry_detections_and_image_synchronized(monkeypatch):
    worker = preview.PreviewWorker("camera")
    camera = {"kind": "video", "gate": [.1, .5, .9, .5], "roi": [0, 0, 1, 1], "confidence": .3}
    coordinates = iter([.43, .49, .55])
    monkeypatch.setattr(preview.detector, "detect", lambda *args: [{"box": [.26, (y := next(coordinates)) - .04, .34, y + .04], "class": "car", "confidence": .9}])
    tracker = preview.Tracker(camera["gate"])
    image = np.full((120, 200, 3), 140, np.uint8)
    for index in range(3):
        worker.publish(image, camera, index / 8, tracker, None)
    result = worker.read()
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(result["image"].split(",")[1]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (result["height"], result["width"])
    assert result["gate"] == camera["gate"] and result["roi"] == camera["roi"]
    assert result["crossings"] == 1
    assert result["direction"] == {"a_to_b": 1, "b_to_a": 0}
    assert result["detections"][0]["track_id"] == 1
    assert result["detections"][0]["counted"] is True
    assert len(result["detections"][0]["trail"]) == 3
    assert worker.read(result["sequence"]) == {"sequence": result["sequence"], "unchanged": True}
    # The preview never calls the persistent observation writer.
    assert result.get("run_id") is None


def test_still_preview_does_not_infer_crossings_or_track_ids(monkeypatch):
    worker = preview.PreviewWorker("camera")
    camera = {"kind": "snapshot", "gate": [.1, .5, .9, .5], "roi": [0, 0, 1, 1], "confidence": .3}
    monkeypatch.setattr(preview.detector, "detect", lambda *args: [{"box": [.1, .1, .2, .2], "class": "car", "confidence": .9}])
    worker.publish(np.zeros((100, 100, 3), np.uint8), camera, 0, None, None)
    result = worker.read()
    assert result["visible"] == 1
    assert result["crossings"] is None and result["direction"] is None
    assert "track_id" not in result["detections"][0]


def test_finished_clip_waits_for_new_media_without_replaying(monkeypatch, tmp_path):
    video = tmp_path / "source.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 8, (160, 120))
    assert writer.isOpened()
    for _ in range(6):
        writer.write(np.full((120, 160, 3), 140, np.uint8))
    writer.release()
    camera = {"kind": "video", "stream_url": "https://example.com/camera.mp4", "gate": [.1, .5, .9, .5], "roi": [0, 0, 1, 1], "confidence": .3}
    monkeypatch.setattr(preview.storage, "get_camera", lambda _: camera)
    monkeypatch.setattr(preview, "download", lambda *args, **kwargs: (video.read_bytes(), {}))
    coordinates = iter([.43, .49, .55, .55, .55, .55] * 2)
    monkeypatch.setattr(preview.detector, "detect", lambda *args: [{"box": [.26, (y := next(coordinates)) - .04, .34, y + .04], "class": "car", "confidence": .9}])
    worker = preview.PreviewWorker("camera")
    frames = []
    publish = worker.publish

    def record(*args):
        publish(*args)
        result = worker.read()
        frames.append(result)

    monkeypatch.setattr(worker, "publish", record)
    original_status=worker.status
    def status(state, message):
        original_status(state,message)
        if state=="waiting": worker.stop.set()
    monkeypatch.setattr(worker,"status",status)
    worker.video()
    assert any(frame["crossings"] == 1 for frame in frames if frame["pass_number"] == 1)
    assert all(frame["replay"] is False and frame["pass_number"] == 1 for frame in frames)
    assert worker.read()["status"] == "waiting"


def test_provider_error_is_recoverable_and_does_not_publish_a_fake_frame(monkeypatch):
    worker = preview.PreviewWorker("camera")
    monkeypatch.setattr(preview.storage, "get_camera", lambda _: {"kind": "snapshot"})
    monkeypatch.setattr(worker, "snapshots", lambda: (_ for _ in ()).throw(ValueError("provider offline")))
    monkeypatch.setattr(worker.stop, "wait", lambda _: worker.stop.set())
    worker.run()
    assert worker.read()["status"] == "error"
    assert worker.read()["image"] is None


def test_unchanged_snapshot_does_not_repeat_inference(monkeypatch):
    worker = preview.PreviewWorker("camera")
    camera = {"kind": "snapshot", "source_url": "https://example.com/camera.jpg", "gate": [.1, .5, .9, .5], "roi": [0, 0, 1, 1], "confidence": .3}
    ok, encoded = cv2.imencode(".jpg", np.full((100, 160, 3), 100, np.uint8))
    assert ok
    monkeypatch.setattr(preview.storage, "get_camera", lambda _: camera)
    monkeypatch.setattr(preview, "download", lambda *args, **kwargs: (encoded.tobytes(), {}))
    inference = []
    monkeypatch.setattr(preview.detector, "detect", lambda *args: inference.append(args) or [])
    checks = []

    def wait(_):
        checks.append(1)
        if len(checks) == 2:
            worker.stop.set()

    monkeypatch.setattr(worker.stop, "wait", wait)
    worker.snapshots()
    assert len(inference) == 1
    assert worker.read()["status"] == "waiting"
    assert worker.read()["image"].startswith("data:image/jpeg;base64,")


def test_configuration_change_reprocesses_an_unchanged_snapshot(monkeypatch):
    worker = preview.PreviewWorker("camera")
    camera = {"kind": "snapshot", "source_url": "https://example.com/camera.jpg", "gate": [.1, .5, .9, .5], "roi": [0, 0, 1, 1], "confidence": .3}
    ok, encoded = cv2.imencode(".jpg", np.full((100, 160, 3), 100, np.uint8))
    assert ok
    monkeypatch.setattr(preview.storage, "get_camera", lambda _: camera)
    monkeypatch.setattr(preview, "download", lambda *args, **kwargs: (encoded.tobytes(), {}))
    inference = []
    monkeypatch.setattr(preview.detector, "detect", lambda *args: inference.append(args[1:]) or [])
    checks = []

    def wait(_):
        checks.append(1)
        if len(checks) == 1:
            camera["confidence"] = .5
            camera["roi"] = [.2, .2, .8, .8]
        else:
            worker.stop.set()

    monkeypatch.setattr(worker.stop, "wait", wait)
    worker.snapshots()
    assert len(inference) == 2
    assert worker.read()["configuration_version"] == 2
    assert worker.read()["confidence"] == .5
    assert worker.read()["roi"] == [.2, .2, .8, .8]
