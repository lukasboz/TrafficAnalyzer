from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from backend import streams, camera_sources, network


def test_signed_playlist_rewrites_nested_segments_maps_and_keys():
    manifest = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example/public.key"\n#EXTINF:6,\n../chunks/1.ts?x=a&y=b\n'
    result = streams.rewrite_playlist(manifest, "https://camera.example/hls/main.m3u8", "caltrans-1")
    assert "camera.example" not in result and "keys.example" not in result
    references = [*streams.URI.findall(result), result.splitlines()[-1]]
    urls = [streams.resource_url("caltrans-1", parse_qs(urlsplit(ref).query)["resource"][0]) for ref in references]
    assert urls == ["https://camera.example/hls/init.mp4", "https://keys.example/public.key", "https://camera.example/chunks/1.ts?x=a&y=b"]


def test_tokens_cannot_be_forged_reused_for_another_camera_or_used_after_expiry(monkeypatch):
    monkeypatch.setattr(streams.time, "time", lambda: 1000)
    token = streams.resource_token("one", "https://example.com/segment.ts")
    with pytest.raises(ValueError): streams.resource_url("two", token)
    with pytest.raises(ValueError): streams.resource_url("one", token[:-1] + ("1" if token[-1] != "1" else "2"))
    monkeypatch.setattr(streams.time, "time", lambda: 9000)
    with pytest.raises(ValueError): streams.resource_url("one", token)


@pytest.mark.parametrize("uri", ["file:///etc/passwd", "data:video/mp4,a", "https://user:secret@example.com/segment", "http://example.com:8080/segment"])
def test_playlist_rejects_nonpublic_protocols_and_credentials(uri):
    with pytest.raises(ValueError): streams.rewrite_playlist("#EXTM3U\n" + uri, "https://example.com/", "one")


def test_every_signed_segment_download_still_checks_dns_and_redirects(monkeypatch):
    checked=[]
    client_type=httpx.Client
    def validate(url):
        checked.append(url)
        if "127.0.0.1" in url: raise ValueError("private source")
    def handle(request):
        return httpx.Response(302, headers={"location":"http://127.0.0.1/private"})
    monkeypatch.setattr(network,"validate_url",validate)
    monkeypatch.setattr(network.httpx,"Client",lambda **kw: client_type(transport=httpx.MockTransport(handle),**kw))
    camera={"id":"one","stream_url":"https://example.com/live.m3u8"}
    token=streams.resource_token("one","https://example.com/segment.ts")
    with pytest.raises(ValueError,match="private"): streams.hls_resource(camera,token)
    assert checked==["https://example.com/segment.ts","http://127.0.0.1/private"]


def test_master_playlist_uses_redirect_destination_for_relative_renditions(monkeypatch):
    calls=[]
    def download(url,**kw):
        calls.append(url)
        if len(calls)==1:
            return b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000\nhigh.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=400000\nlow.m3u8\n', {"x-source-url":"https://cdn.example/new/master.m3u8"}
        return b'#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:42\n#EXT-X-PROGRAM-DATE-TIME:2026-10-05T20:00:00Z\n#EXTINF:6,\n42.ts\n#EXTINF:6,\n43.ts\n',{}
    monkeypatch.setattr(streams,"download",download)
    text,base,_=streams.media_playlist({"stream_url":"https://camera.example/master.m3u8"})
    assert calls[1]=="https://cdn.example/new/low.m3u8"
    rows=streams.segments(text,base)
    assert [r["sequence"] for r in rows]==[42,43]
    assert rows[1]["stamp"]-rows[0]["stamp"]==timedelta(seconds=6)
    assert rows[0]["url"]=="https://cdn.example/new/42.ts"


def test_live_window_consumes_only_new_segments_without_replaying(monkeypatch):
    playlists=iter([
        "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:40\n#EXTINF:6,\n40.ts\n#EXTINF:6,\n41.ts\n",
        "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:40\n#EXTINF:6,\n40.ts\n#EXTINF:6,\n41.ts\n",
        "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:41\n#EXTINF:6,\n41.ts\n#EXTINF:6,\n42.ts\n",
    ])
    monkeypatch.setattr(streams,"media_playlist",lambda _: (next(playlists),"https://camera.example/live.m3u8",{}))
    now=[0]
    monkeypatch.setattr(streams.time,"monotonic",lambda:now[0])
    monkeypatch.setattr(streams.time,"sleep",lambda value:now.__setitem__(0,now[0]+value))
    rows=list(streams.hls_window({},12))
    assert [r[0]["sequence"] for r in rows]==[41,42]


def test_recent_clip_rejects_old_provider_timestamps_and_keeps_unknown_explicit():
    stale=format_datetime(datetime.now(timezone.utc)-timedelta(minutes=6),usegmt=True)
    with pytest.raises(ValueError,match="five minutes"): streams.check_recent({"last-modified":stale})
    fresh=format_datetime(datetime.now(timezone.utc)-timedelta(seconds=30),usegmt=True)
    assert streams.check_recent({"last-modified":fresh}) is not None
    assert streams.check_recent({}) is None


def test_hls_playback_rejects_ended_or_stale_playlists(monkeypatch):
    camera={"id":"one","stream_url":"https://camera.example/live.m3u8"}
    monkeypatch.setattr(streams,"download",lambda *a,**kw: (b"#EXTM3U\n#EXTINF:6,\n1.ts\n#EXT-X-ENDLIST\n",{}))
    with pytest.raises(ValueError,match="ended"): streams.hls_resource(camera)
    stamp=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(streams,"download",lambda *a,**kw: (f"#EXTM3U\n#EXT-X-PROGRAM-DATE-TIME:{stamp}\n#EXTINF:6,\n1.ts\n".encode(),{}))
    with pytest.raises(ValueError,match="five minutes"): streams.hls_resource(camera)


def test_hls_resource_supports_fragment_byte_ranges_without_forwarding_arbitrary_requests(monkeypatch):
    import importlib
    from starlette.requests import Request
    from fastapi import HTTPException
    api=importlib.import_module("backend.app")
    monkeypatch.setattr(api,"require_camera",lambda _: {"id":"one","feed_type":"hls"})
    monkeypatch.setattr(api,"hls_resource",lambda *a: (b"0123456789","video/mp4"))
    def request(value):
        return Request({"type":"http","headers":[(b"range",value.encode())]})
    response=api.hls("one",request("bytes=2-5"),"signed")
    assert response.status_code==206 and response.body==b"2345"
    assert response.headers["content-range"]=="bytes 2-5/10"
    with pytest.raises(HTTPException) as exc: api.hls("one",request("bytes=20-30"),"signed")
    assert exc.value.status_code==416


def test_hls_recording_downloads_segments_before_next_playlist_and_decodes_only_local_files(monkeypatch,tmp_path):
    fetched=[]
    def rows(*args):
        yield {"url":"https://example.com/1.ts","init":None,"duration":6,"stamp":None},{}
        assert fetched==["https://example.com/1.ts"]
        yield {"url":"https://example.com/2.ts","init":None,"duration":6,"stamp":None},{}
    @contextmanager
    def segment(row):
        fetched.append(row["url"])
        path=tmp_path/"segment.ts"
        path.write_bytes(b"media")
        yield path,{}
    def execute(command,**kw):
        from pathlib import Path
        playlist=Path(command[command.index("-i")+1]).read_text()
        assert "https:" not in playlist and "segment-0.ts" in playlist
        assert command[command.index("-protocol_whitelist")+1]=="file"
        assert command[command.index("-t")+1]=="10"
        Path(command[-1]).write_bytes(b"recording")
        return type("Result",(),{"returncode":0})()
    monkeypatch.setattr(streams,"hls_window",rows)
    monkeypatch.setattr(streams,"local_segment",segment)
    monkeypatch.setattr(streams.shutil,"which",lambda _:"ffmpeg")
    monkeypatch.setattr(streams.subprocess,"run",execute)
    with streams.recorded_hls({},10) as (path,_):
        assert path.read_bytes()==b"recording"
    assert not path.exists()


def test_mjpeg_parser_handles_split_markers_multiple_frames_and_closes_source(monkeypatch):
    closed=[]
    class Response:
        headers={"content-type":"multipart/x-mixed-replace; boundary=cam"}
        def iter_bytes(self,chunk_size):
            yield b"--cam\r\nContent-Type: image/jpeg\r\n\r\n\xff"
            yield b"\xd8first\xff"
            yield b"\xd9\r\n--cam\r\n\xff\xd8second\xff\xd9"
    @contextmanager
    def opened(*a,**kw):
        try: yield Response()
        finally: closed.append(True)
    monkeypatch.setattr(streams,"open_media",opened)
    assert list(streams.jpeg_frames("https://example.com/stream")) == [b"\xff\xd8first\xff\xd9",b"\xff\xd8second\xff\xd9"]
    assert closed==[True]


def test_norway_preserves_live_hls_while_still_only_cameras_remain_snapshots(monkeypatch):
    def row(key,**props):
        return {"geometry":{"coordinates":[5.34,60.37]},"properties":{"cameraId":key,"description":"Fjosangerveien","stillImageUrl":"https://camera.example/still.jpg",**props}}
    monkeypatch.setattr(camera_sources,"fetch_json",lambda _: {"features":[row("1",videoUrl="https://camera.example/live.m3u8"),row("2")]})
    cameras=list(camera_sources.norway())
    assert [c["feed_type"] for c in cameras]==["hls","snapshot"]
