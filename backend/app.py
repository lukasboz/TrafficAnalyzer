import csv
import hashlib
import io
import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from typing import Literal
import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from . import storage
from .config import API_KEY, FRAMES
from .engine import service, enqueue, next_fire
from .network import download, validate_url
from .providers import PROVIDERS, import_provider, snapshot_url
from .vision import detector
from .live import live, PreviewBusy
from .streams import feed_type, clip_download, hls_resource, jpeg_frames


@asynccontextmanager
async def lifespan(app):
    storage.init()
    service.start()
    live.start()
    yield
    live.close()
    service.close()


app=FastAPI(title="Flowstate Traffic Analysis",version="1.0.0",lifespan=lifespan)


@app.middleware("http")
async def authenticate(request: Request,call_next):
    if API_KEY and request.url.path!="/health" and not secrets.compare_digest(request.headers.get("x-flowstate-key",""),API_KEY):
        return JSONResponse({"detail":"An analysis service key is required."},status_code=401)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Cache-Control"]="no-store"
    return response


@app.exception_handler(ValueError)
async def value_error(request,exc):
    return JSONResponse({"detail":str(exc)},status_code=400)


@app.get("/health")
def health():
    return {"status":"ok"}


@app.get("/api/health")
def health_detail():
    with storage.connect() as con:
        cameras=con.execute("SELECT COUNT(*) FROM cameras").fetchone()[0]
        runs=con.execute("SELECT status,COUNT(*) AS n FROM runs GROUP BY status").fetchall()
    return {"status":"ok","model":"YOLOX Tiny · COCO","model_ready":detector.session is not None,"model_error":detector.error,
            "cameras":cameras,"runs":{r[0]:r[1] for r in runs},"scheduler":"running" if service.thread and service.thread.is_alive() else "stopped",
            "time":storage.now(),"provider_errors":service.bootstrap_errors,"workers":2}


class CameraInput(BaseModel):
    name: str=Field(min_length=2,max_length=120)
    city: str=Field(default="",max_length=100)
    country: str=Field(min_length=2,max_length=100)
    lat: float=Field(ge=-90,le=90)
    lon: float=Field(ge=-180,le=180)
    timezone: str="UTC"
    source_url: str=Field(max_length=2048)
    stream_url: str|None=Field(default=None,max_length=2048)
    kind: Literal["snapshot","video"]="snapshot"
    feed_type: Literal["snapshot","clip","hls","mjpeg"]|None=None

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls,value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError):
            raise ValueError("Enter a valid IANA timezone, such as Europe/London.")
        return value

    @model_validator(mode="after")
    def video_valid(self):
        if self.kind=="video" and not self.stream_url:
            raise ValueError("Video cameras require a direct video URL.")
        if self.kind == "snapshot":
            self.feed_type = "snapshot"
        else:
            self.feed_type = self.feed_type or ("hls" if self.stream_url.split("?")[0].lower().endswith(".m3u8") else "clip")
            if self.feed_type == "snapshot":
                raise ValueError("Choose a video feed type for video cameras.")
        return self


class CameraPatch(BaseModel):
    saved: bool|None=None
    gate: list[float]|None=None
    roi: list[float]|None=None
    confidence: float|None=Field(default=None,ge=0.1,le=0.9)
    timezone: str|None=None

    @field_validator("gate","roi")
    @classmethod
    def geometry(cls,value):
        if value is not None and (len(value)!=4 or any(not 0<=v<=1 for v in value)):
            raise ValueError("Geometry must contain four normalized coordinates between zero and one.")
        return value

    @model_validator(mode="after")
    def nonempty(self):
        if self.roi and (self.roi[0]>=self.roi[2] or self.roi[1]>=self.roi[3]):
            raise ValueError("The analysis area must have positive width and height.")
        if self.gate and np.linalg.norm(np.array(self.gate[:2])-self.gate[2:])<0.05:
            raise ValueError("The counting line must be at least 5% of the image width or height.")
        if self.timezone:
            CameraInput.timezone_valid(self.timezone)
        return self


class RunOptions(BaseModel):
    mode: Literal["video","snapshot"]="video"
    duration: int=Field(default=30,ge=0,le=300)
    interval: int=Field(default=5,ge=3,le=60)

    @model_validator(mode="after")
    def nonzero_video(self):
        if self.mode=="video" and self.duration<1:
            raise ValueError("Video analysis requires a positive duration.")
        return self


class ScheduleInput(BaseModel):
    camera_id: str
    name: str=Field(min_length=1,max_length=100)
    time: str=Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str
    days: list[int]=Field(min_length=1,max_length=7)
    enabled: bool=True
    options: RunOptions

    @field_validator("days")
    @classmethod
    def valid_days(cls,value):
        if any(d not in range(7) for d in value):
            raise ValueError("Weekdays are numbered 0 (Monday) through 6 (Sunday).")
        return sorted(set(value))

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls,value):
        return CameraInput.timezone_valid(value)


def require_camera(camera_id):
    camera=storage.get_camera(camera_id)
    if not camera:
        raise HTTPException(404,"Camera not found.")
    return camera


@app.get("/api/cameras")
def cameras(search: str="",provider: str="",saved: bool=False,limit: int=Query(2500,ge=1,le=4000),offset: int=Query(0,ge=0)):
    clauses=[]
    args=[]
    if search:
        clauses.append("lower(c.data) LIKE ?")
        args.append("%"+search.lower()+"%")
    if provider:
        clauses.append("json_extract(c.data,'$.provider')=?")
        args.append(provider)
    if saved:
        clauses.append("c.saved=1")
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    with storage.connect() as con:
        total=con.execute("SELECT COUNT(*) FROM cameras c"+where,args).fetchone()[0]
        rows=con.execute("SELECT c.*,r.metrics,r.finished_at FROM cameras c LEFT JOIN runs r ON r.id=(SELECT id FROM runs WHERE camera_id=c.id AND status='completed' ORDER BY created_at DESC LIMIT 1)"+
                         where+" ORDER BY c.saved DESC,json_extract(c.data,'$.name'),c.id LIMIT ? OFFSET ?",(*args,limit,offset)).fetchall()
    return {"items":[{**storage.camera(r),"latest_metrics":json.loads(r["metrics"]) if r["metrics"] else None,"last_analyzed":r["finished_at"]} for r in rows],"total":total}


@app.post("/api/cameras",status_code=201)
def add_camera(body: CameraInput):
    validate_url(body.source_url)
    if body.stream_url:
        validate_url(body.stream_url)
    camera={**body.model_dump(),"id":"custom-"+str(uuid.uuid4()),"provider":"custom","gate":[0.15,0.6,0.85,0.6],"roi":[0,0,1,1],"confidence":0.3}
    storage.put_cameras([camera])
    with storage.connect() as con:
        con.execute("UPDATE cameras SET saved=1 WHERE id=?",(camera["id"],))
    return storage.get_camera(camera["id"])


@app.patch("/api/cameras/{camera_id}")
def patch_camera(camera_id,body:CameraPatch):
    camera=require_camera(camera_id)
    values=body.model_dump(exclude_none=True)
    saved=values.pop("saved",camera["saved"])
    camera.update(values)
    with storage.connect() as con:
        con.execute("UPDATE cameras SET data=?,saved=? WHERE id=?",(json.dumps(camera),int(saved),camera_id))
    return storage.get_camera(camera_id)


_snapshot_cache={}
_snapshot_lock=__import__('threading').Lock()


@app.get("/api/cameras/{camera_id}/snapshot")
def snapshot(camera_id):
    c=require_camera(camera_id)
    with _snapshot_lock:
        cached=_snapshot_cache.get(camera_id)
    if cached and time.monotonic()-cached[0]<10:
        return Response(cached[1],media_type="image/jpeg")
    try:
        media,headers=download(snapshot_url(c),limit=15_000_000,timeout=15)
        frame=cv2.imdecode(np.frombuffer(media,np.uint8),cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("The camera did not return an image.")
        h,w=frame.shape[:2]
        if w>1280:
            frame=cv2.resize(frame,(1280,round(h*1280/w)))
        ok,encoded=cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,80])
        result=encoded.tobytes()
        with _snapshot_lock:
            if len(_snapshot_cache)>50:
                _snapshot_cache.pop(next(iter(_snapshot_cache)))
            _snapshot_cache[camera_id]=(time.monotonic(),result)
        return Response(result,media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(502,"Camera image unavailable. The provider may be offline or changing the feed.") from exc


@app.get("/api/cameras/{camera_id}/clip")
def clip(camera_id):
    c=require_camera(camera_id)
    if feed_type(c) != "clip":
        raise HTTPException(400,"Select the live video feed for this camera.")
    try:
        data,headers=clip_download(c)
        outgoing={"Content-Length":str(len(data)), "X-Source-Timestamp":headers.get("last-modified", "unknown")}
        return Response(data,media_type="video/mp4",headers=outgoing)
    except Exception as exc:
        raise HTTPException(502,str(exc)[:250]) from exc


@app.get("/api/cameras/{camera_id}/hls")
def hls(camera_id, request: Request, resource: str|None=Query(None,max_length=6500)):
    c=require_camera(camera_id)
    if feed_type(c) != "hls":
        raise HTTPException(400,"This camera does not publish HLS video.")
    try:
        data,content_type=hls_resource(c,resource)
        if resource and request.headers.get("range") and content_type != "application/vnd.apple.mpegurl":
            match=re.fullmatch(r"bytes=(\d+)-(\d*)",request.headers["range"])
            if not match:
                raise HTTPException(416,"Only a single explicit media range is supported.",headers={"Content-Range":f"bytes */{len(data)}"})
            start=int(match[1])
            end=min(int(match[2]) if match[2] else len(data)-1,len(data)-1)
            if start>end or start>=len(data):
                raise HTTPException(416,"This media range is unavailable.",headers={"Content-Range":f"bytes */{len(data)}"})
            return Response(data[start:end+1],status_code=206,media_type=content_type,
                            headers={"Accept-Ranges":"bytes","Content-Range":f"bytes {start}-{end}/{len(data)}"})
        return Response(data,media_type=content_type)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502,str(exc)[:250]) from exc


@app.get("/api/cameras/{camera_id}/mjpeg")
def mjpeg(camera_id):
    c=require_camera(camera_id)
    if feed_type(c) != "mjpeg":
        raise HTTPException(400,"This camera does not publish MJPEG video.")
    iterator=jpeg_frames(c["stream_url"],duration=50)
    try:
        first=next(iterator)
    except Exception as exc:
        iterator.close()
        raise HTTPException(502,"The live camera is unavailable. Please retry.") from exc
    def frames():
        try:
            for frame in __import__('itertools').chain([first],iterator):
                yield b"--flowstate\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
        finally:
            iterator.close()
    return StreamingResponse(frames(),media_type="multipart/x-mixed-replace; boundary=flowstate")


@app.post("/api/cameras/{camera_id}/live")
def start_live(camera_id):
    require_camera(camera_id)
    try:
        return live.create(camera_id)
    except PreviewBusy as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "2"}) from exc


@app.get("/api/live/{session_id}/frame")
def live_frame(session_id, after: int=Query(-1, ge=-1)):
    try:
        return live.frame(session_id, after)
    except LookupError as exc:
        raise HTTPException(410, str(exc)) from exc


@app.delete("/api/live/{session_id}")
def stop_live(session_id):
    live.release(session_id)
    return {"ok": True}


@app.get("/api/providers")
def providers():
    with storage.connect() as con:
        counts={r[0]:r[1] for r in con.execute("SELECT json_extract(data,'$.provider'),COUNT(*) FROM cameras GROUP BY 1")}
    statuses=storage.provider_statuses()
    return [{**p,"count":counts.get(p["id"],0),**{k:v for k,v in statuses.get(p["id"],{}).items() if k!="id"}} for p in PROVIDERS]


@app.post("/api/providers/{provider_id}/refresh")
def refresh(provider_id):
    try:
        return {"imported":import_provider(provider_id)}
    except Exception as exc:
        raise HTTPException(502,f"Could not refresh this directory: {str(exc)[:200]}") from exc


@app.post("/api/cameras/{camera_id}/analyze",status_code=202)
def start(camera_id,options: RunOptions):
    c=require_camera(camera_id)
    if options.mode=="video" and c["kind"]!="video":
        raise HTTPException(400,"This camera supports snapshots only.")
    run_id=enqueue(camera_id,options.model_dump())
    return {"id":run_id,"status":"queued"}


@app.get("/api/runs")
def runs(camera_id: str="",status: str="",days:int=Query(30,ge=1,le=3650),limit:int=Query(150,ge=1,le=1000)):
    clauses=["r.created_at>=?"]
    args=[(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()]
    if camera_id:
        clauses.append("r.camera_id=?")
        args.append(camera_id)
    if status:
        clauses.append("r.status=?")
        args.append(status)
    with storage.connect() as con:
        rows=con.execute("SELECT r.*,json_extract(c.data,'$.name') AS camera_name,json_extract(c.data,'$.timezone') AS camera_timezone FROM runs r JOIN cameras c ON c.id=r.camera_id WHERE "+" AND ".join(clauses)+" ORDER BY created_at DESC LIMIT ?",(*args,limit)).fetchall()
    return [storage.run(r) for r in rows]


@app.get("/api/runs/{run_id}")
def get_run(run_id):
    with storage.connect() as con:
        row=con.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row:
            raise HTTPException(404,"Analysis not found.")
        samples=con.execute("SELECT * FROM samples WHERE run_id=? ORDER BY elapsed",(run_id,)).fetchall()
    return {**storage.run(row),"samples":[{**dict(s),"counts":json.loads(s["counts"])} for s in samples]}


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id):
    with storage.connect() as con:
        row=con.execute("SELECT status FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row:
            raise HTTPException(404,"Analysis not found.")
        if row[0] in ("queued","running"):
            con.execute("UPDATE runs SET status='cancelled',finished_at=? WHERE id=?",(storage.now(),run_id))
    return {"status":"cancelled" if row[0] in ("queued","running") else row[0]}


@app.get("/api/runs/{run_id}/frame")
def frame(run_id):
    with storage.connect() as con:
        row=con.execute("SELECT frame FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404,"No analyzed frame available.")
    path=FRAMES/(run_id+".jpg")
    if not path.exists():
        raise HTTPException(404,"The analyzed frame is no longer available.")
    return FileResponse(path,media_type="image/jpeg")


def schedule_rows():
    with storage.connect() as con:
        rows=con.execute("SELECT s.*,json_extract(c.data,'$.name') AS camera_name FROM schedules s JOIN cameras c ON c.id=s.camera_id").fetchall()
    return [{**json.loads(r["data"]),"id":r["id"],"camera_name":r["camera_name"],"next_run":next_fire(json.loads(r["data"])) if json.loads(r["data"])["enabled"] else None} for r in rows]


@app.get("/api/schedules")
def schedules():
    return schedule_rows()


@app.post("/api/schedules",status_code=201)
def add_schedule(body:ScheduleInput):
    c=require_camera(body.camera_id)
    if body.options.mode=="video" and c["kind"]!="video":
        raise HTTPException(400,"This camera supports snapshots only.")
    schedule_id=str(uuid.uuid4())
    with storage.connect() as con:
        con.execute("INSERT INTO schedules VALUES(?,?,?)",(schedule_id,body.camera_id,json.dumps(body.model_dump())))
    return next(r for r in schedule_rows() if r["id"]==schedule_id)


class ScheduleToggle(BaseModel):
    enabled: bool


@app.patch("/api/schedules/{schedule_id}")
def toggle_schedule(schedule_id,body:ScheduleToggle):
    with storage.connect() as con:
        row=con.execute("SELECT data FROM schedules WHERE id=?",(schedule_id,)).fetchone()
        if not row:
            raise HTTPException(404,"Schedule not found.")
        data=json.loads(row[0])
        data["enabled"]=body.enabled
        con.execute("UPDATE schedules SET data=? WHERE id=?",(json.dumps(data),schedule_id))
    return {"enabled":body.enabled}


@app.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id):
    with storage.connect() as con:
        count=con.execute("DELETE FROM schedules WHERE id=?",(schedule_id,)).rowcount
    if not count:
        raise HTTPException(404,"Schedule not found.")
    return {"deleted":True}


@app.get("/api/reports")
def report(camera_id: str="",days:int=Query(7,ge=1,le=3650)):
    completed=runs(camera_id=camera_id,status="completed",days=days,limit=1000)
    buckets={}
    for r in completed:
        local=datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo(r["camera_timezone"]))
        hour=local.hour
        b=buckets.setdefault(hour,{"hour":hour,"runs":0,"visible":[],"occupancy":[],"flow":[]})
        b["runs"]+=1
        b["visible"].append(r["metrics"]["visible_mean"])
        b["occupancy"].append(r["metrics"]["occupancy_mean"])
        if r["metrics"]["flow_per_minute"] is not None:
            b["flow"].append(r["metrics"]["flow_per_minute"])
    hourly=[{"hour":hour,"runs":buckets.get(hour,{}).get("runs",0),**{key:round(float(np.mean(buckets[hour][key])),2) if hour in buckets and buckets[hour][key] else None for key in ("visible","occupancy","flow")}} for hour in range(24)]
    return {"hourly":hourly,"runs":completed,"timezone_note":"Hour of day uses each camera's local timezone.","limited":len(completed)==1000}


@app.get("/api/export.csv")
def export(camera_id: str="",days:int=Query(30,ge=1,le=3650)):
    rows=runs(camera_id=camera_id,days=days,limit=1000)
    out=io.StringIO()
    writer=csv.writer(out)
    writer.writerow(["run_id","camera","camera_id","requested_at_utc","finished_at_utc","status","mode","observed_seconds","sampled_frames","vehicle_crossings","flow_vehicles_per_second","flow_vehicles_per_minute","visible_mean","visible_peak","image_occupancy_percent","cars","motorcycles","buses","trucks","error"])
    def safe(value):
        s=str(value or "")
        return "'"+s if s.startswith(("=","+","-","@","\t","\r")) else s
    for r in rows:
        m=r["metrics"] or {}
        classes=m.get("class_counts",{})
        writer.writerow([r["id"],safe(r["camera_name"]),r["camera_id"],r["created_at"],r["finished_at"],r["status"],r["options"]["mode"],
                         *[m.get(k) for k in ("duration","frames","crossings","flow_per_second","flow_per_minute","visible_mean","visible_peak","occupancy_mean")],
                         *[classes.get(k) for k in ("car","motorcycle","bus","truck")],safe(r["error"])])
    return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=flowstate-traffic.csv"})
