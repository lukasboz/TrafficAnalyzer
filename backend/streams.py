"""Public HLS/MJPEG playback and bounded, local-only video decoding."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urljoin

from .config import API_KEY
from .network import download, open_media
from .camera_sources import public_media_url

SIGNING_KEY = (API_KEY or secrets.token_hex(32)).encode()
MAX_AGE = 300
URI = re.compile(r'URI="([^"\r\n]+)"')


def feed_type(camera):
    return camera.get("feed_type") or ("clip" if camera.get("kind") == "video" else "snapshot")


def modified(headers):
    try:
        return parsedate_to_datetime(headers["last-modified"]).astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def check_recent(headers):
    stamp = modified(headers)
    if stamp and (datetime.now(timezone.utc) - stamp).total_seconds() > MAX_AGE:
        raise ValueError("The provider clip is more than five minutes old. Waiting for a fresh clip.")
    return stamp


def clip_download(camera, timeout=60):
    data, headers = download(camera["stream_url"], limit=80_000_000, timeout=timeout)
    check_recent(headers)
    return data, headers


def resource_token(camera_id, url):
    if not public_media_url(url) or len(url) > 4096:
        raise ValueError("The playlist contains an unsupported media URL.")
    payload = base64.urlsafe_b64encode(json.dumps([camera_id, url, int(time.time()) + 7200], separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def resource_url(camera_id, token):
    try:
        payload, signature = token.rsplit(".", 1)
        expected = hmac.new(SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        owner, url, expiry = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if owner != camera_id or expiry < time.time() or not public_media_url(url):
            raise ValueError()
        return url
    except Exception as exc:
        raise ValueError("This stream resource has expired or is invalid. Reconnect the video feed.") from exc


def playlist_text(data):
    text = data.decode("utf-8-sig")
    if not text.lstrip().startswith("#EXTM3U"):
        raise ValueError("The camera did not return an HLS playlist.")
    return text


def rewrite_playlist(text, base, camera_id):
    def proxied(uri):
        token = resource_token(camera_id, urljoin(base, uri))
        return f"/api/cameras/{quote(camera_id, safe='')}/hls?resource={token}"
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            line = URI.sub(lambda match: f'URI="{proxied(match[1])}"', line)
        elif line:
            line = proxied(line)
        lines.append(line)
    return "\n".join(lines) + "\n"


def hls_resource(camera, token=None):
    url = resource_url(camera["id"], token) if token else camera["stream_url"]
    data, headers = download(url, limit=20_000_000, timeout=20)
    if data.lstrip().startswith(b"#EXTM3U"):
        text = playlist_text(data)
        if "#EXT-X-ENDLIST" in text:
            raise ValueError("This camera stream has ended. Waiting for the provider to resume live video.")
        stamps = re.findall(r"#EXT-X-PROGRAM-DATE-TIME:([^\r\n]+)", text)
        if stamps:
            stamp = datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
            if stamp.tzinfo and (datetime.now(timezone.utc) - stamp).total_seconds() > MAX_AGE:
                raise ValueError("The live stream is more than five minutes behind. Waiting for current video.")
        text = rewrite_playlist(text, headers.get("x-source-url", url), camera["id"])
        return text.encode(), "application/vnd.apple.mpegurl"
    if not token:
        raise ValueError("The provider did not return a live HLS playlist.")
    # Never serve provider HTML or active content under the application's origin.
    content_type = headers.get("content-type", "").split(";")[0]
    safe_types = {"video/mp2t", "video/mp4", "audio/mp4", "audio/aac", "application/octet-stream"}
    return data, content_type if content_type in safe_types else "application/octet-stream"


def media_playlist(camera):
    url = camera["stream_url"]
    for _ in range(4):
        data, headers = download(url, limit=1_000_000, timeout=15)
        base = headers.get("x-source-url", url)
        text = playlist_text(data)
        lines = text.splitlines()
        variants = []
        for i, line in enumerate(lines[:-1]):
            if line.startswith("#EXT-X-STREAM-INF:"):
                bandwidth = re.search(r"(?:^|,)BANDWIDTH=(\d+)", line.partition(":")[2])
                variants.append((int(bandwidth[1]) if bandwidth else 0, urljoin(base, lines[i + 1].strip())))
        if variants:
            url = min(variants)[1]
            if not public_media_url(url):
                raise ValueError("The HLS rendition URL is not supported.")
            continue
        return text, base, headers
    raise ValueError("The HLS playlist has too many nested renditions.")


def segments(text, base):
    sequence = 0
    duration = 0
    stamp = None
    init = None
    discontinuity = False
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-KEY:") and "METHOD=NONE" not in line:
            raise ValueError("Encrypted HLS cannot be analyzed. Video playback remains available.")
        elif line.startswith("#EXT-X-BYTERANGE:"):
            raise ValueError("Byte-range HLS cannot be analyzed. Video playback remains available.")
        elif line.startswith("#EXT-X-MAP:"):
            match = URI.search(line)
            if not match or "BYTERANGE=" in line:
                raise ValueError("The HLS initialization segment is unsupported.")
            init = urljoin(base, match[1])
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            stamp = datetime.fromisoformat(line.split(":", 1)[1].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = None
        elif line == "#EXT-X-DISCONTINUITY":
            discontinuity = True
        elif line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",")[0])
        elif line and not line.startswith("#"):
            if not 0 < duration <= 60:
                raise ValueError("The HLS segment duration is invalid.")
            rows.append({"sequence": sequence, "url": urljoin(base, line), "duration": duration,
                         "stamp": stamp, "init": init, "discontinuity": discontinuity})
            sequence += 1
            if stamp:
                from datetime import timedelta
                stamp += timedelta(seconds=duration)
            discontinuity = False
    if not rows:
        raise ValueError("The live camera has not published any video segments yet.")
    return rows


@contextmanager
def local_segment(row):
    """OpenCV only receives local media, never unchecked playlist URLs."""
    if row["stamp"] and (datetime.now(timezone.utc) - row["stamp"]).total_seconds() > MAX_AGE:
        raise ValueError("The live stream is more than five minutes behind. Reconnect when the provider resumes.")
    with tempfile.TemporaryDirectory(prefix="flowstate-stream-") as directory:
        path = Path(directory) / ("segment.mp4" if row["init"] else "segment.ts")
        data, headers = download(row["url"], limit=20_000_000, timeout=20)
        if row["init"]:
            init, _ = download(row["init"], limit=5_000_000, timeout=15)
            data = init + data
        path.write_bytes(data)
        yield path, headers


def hls_window(camera, duration, stopped=lambda: False):
    """Record new live segments for the requested time; never loop old video."""
    text, base, headers = media_playlist(camera)
    if "#EXT-X-ENDLIST" in text:
        raise ValueError("This HLS feed is an ended recording, rather than a live camera.")
    rows = segments(text, base)
    last = rows[-1]["sequence"] - 1
    measured = 0
    deadline = time.monotonic() + duration + 60
    advanced = time.monotonic()
    count = 0
    while measured < duration and time.monotonic() < deadline and not stopped():
        new = [row for row in rows if row["sequence"] > last]
        for row in new:
            if row["discontinuity"] and count:
                return
            yield row, headers
            count += 1
            last = row["sequence"]
            measured += row["duration"]
            advanced = time.monotonic()
            if measured >= duration:
                break
        if measured >= duration:
            break
        until = time.monotonic() + min(2, rows[-1]["duration"])
        while time.monotonic() < until and not stopped():
            time.sleep(0.2)
        if stopped():
            return
        text, base, headers = media_playlist(camera)
        rows = segments(text, base)
        if rows[0]["sequence"] > last + 1 or rows[-1]["sequence"] < last:
            raise ValueError("The live camera dropped video segments. Please retry the observation.")
        if time.monotonic() - advanced > 30:
            raise ValueError("The live camera stopped publishing new video.")
    if measured < min(duration, 2):
        raise ValueError("The live camera stopped publishing new video.")


@contextmanager
def recorded_hls(camera, duration, stopped=lambda: False):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("Live HLS analysis requires ffmpeg on the analysis service.")
    # Download each segment as it becomes available, before it ages out of the CDN.
    with tempfile.TemporaryDirectory(prefix="flowstate-recording-") as directory:
        root = Path(directory)
        manifest = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:60"]
        total_size = 0
        first = None
        headers = {}
        for i, (row, _) in enumerate(hls_window(camera, min(duration, 300), stopped)):
            if first is None:
                first = row
            if row["init"]:
                raise ValueError("Fragmented MP4 HLS analysis is not supported yet. Live playback is available.")
            with local_segment(row) as (path, segment_headers):
                local = root / f"segment-{i}{path.suffix}"
                shutil.copyfile(path, local)
                total_size += local.stat().st_size
                if total_size > 80_000_000:
                    raise ValueError("The live observation exceeded the 80 MB recording limit. Choose a shorter duration.")
            manifest.extend([f"#EXTINF:{row['duration']},", local.name])
            headers = segment_headers
        manifest.append("#EXT-X-ENDLIST")
        if stopped():
            raise ValueError("The live observation was cancelled.")
        if first is None:
            raise ValueError("No live video segments were recorded.")
        playlist = root / "local.m3u8"
        playlist.write_text("\n".join(manifest), encoding="utf-8")
        target = root / "recording.mp4"
        command = [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-allowed_extensions", "ALL",
                   "-i", str(playlist), "-t", str(duration), "-c", "copy", "-movflags", "+faststart", "-y", str(target)]
        result = subprocess.run(command, capture_output=True, timeout=45)
        if result.returncode or not target.exists():
            raise ValueError("The public live stream could not be decoded into an observation.")
        if first["stamp"]:
            headers["last-modified"] = first["stamp"].astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        yield target, headers


def jpeg_frames(url, stop=None, duration=300):
    started = time.monotonic()
    with open_media(url, timeout=12) as response:
        content_type = response.headers.get("content-type", "").lower()
        if "multipart/x-mixed-replace" not in content_type:
            raise ValueError("The provider did not return a live MJPEG stream.")
        buffer = bytearray()
        for chunk in response.iter_bytes(chunk_size=4096):
            if (stop and stop()) or time.monotonic() - started > duration:
                return
            buffer.extend(chunk)
            if len(buffer) > 5_000_000:
                raise ValueError("A live camera frame exceeded the size limit.")
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(buffer) > 8192:
                        del buffer[:-1]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                yield frame
