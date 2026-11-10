import json
import logging
import hashlib
import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from contextlib import ExitStack
import cv2
import numpy as np
from . import storage
from .config import FRAMES
from .network import download
from .vision import detector, Tracker, occupancy, VEHICLES
from .streams import feed_type, check_recent, recorded_hls, jpeg_frames

log = logging.getLogger("flowstate")


def enqueue(camera_id, options, schedule_id=None, slot=None):
    run_id=str(uuid.uuid4())
    camera=storage.get_camera(camera_id)
    if not camera:
        raise ValueError("Camera not found.")
    options={**options,"configuration":{k:camera[k] for k in ("gate","roi","confidence","source_url","stream_url")},"feed_type":feed_type(camera)}
    with storage.connect() as con:
        if schedule_id and con.execute("SELECT id FROM runs WHERE schedule_id=? AND slot=?",(schedule_id,slot)).fetchone():
            return None
        try:
            con.execute("INSERT INTO runs(id,camera_id,status,created_at,options,schedule_id,slot) VALUES(?,?,'queued',?,?,?,?)",
                        (run_id,camera_id,storage.now(),json.dumps(options),schedule_id,slot))
        except sqlite3.IntegrityError:
            # Concurrent requests share the same active run, without launching duplicates.
            active=con.execute("SELECT id FROM runs WHERE camera_id=? AND status IN ('queued','running')",(camera_id,)).fetchone()
            return active[0] if active else None
    return run_id


def due_slot(schedule, now):
    local=now.astimezone(ZoneInfo(schedule["timezone"]))
    if local.weekday() not in schedule["days"]:
        return None
    hour,minute=map(int,schedule["time"].split(":"))
    target=local.replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0)
    # Skip nonexistent clock times at the spring DST change.
    if target.astimezone(timezone.utc).astimezone(local.tzinfo).replace(tzinfo=None)!=target.replace(tzinfo=None):
        return None
    age=(now-target.astimezone(timezone.utc)).total_seconds()
    return f"{local.date()}T{schedule['time']}" if 0<=age<600 else None


def next_fire(schedule, now=None):
    now=now or datetime.now(timezone.utc)
    local=now.astimezone(ZoneInfo(schedule["timezone"]))
    hour,minute=map(int,schedule["time"].split(":"))
    for offset in range(9):
        day=local+timedelta(days=offset)
        target=day.replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0)
        roundtrip=target.astimezone(timezone.utc).astimezone(local.tzinfo)
        if target.weekday() in schedule["days"] and target.astimezone(timezone.utc)>now and roundtrip.replace(tzinfo=None)==target.replace(tzinfo=None):
            return target.isoformat()
    return None


def save_frame(run_id, frame, detections):
    h,w=frame.shape[:2]
    if w>1280:
        frame=cv2.resize(frame,(1280,round(h*1280/w)))
    path=FRAMES/(run_id+".jpg")
    cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,85])
    storage.update_run(run_id,frame=str(path),detections=detections)


def cancelled(run_id):
    with storage.connect() as con:
        row=con.execute("SELECT status FROM runs WHERE id=?",(run_id,)).fetchone()
    return not row or row[0]=="cancelled"


def analyze(run_id):
    cap=None
    temp=None
    contexts=ExitStack()
    try:
        with storage.connect() as con:
            row=con.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row or cancelled(run_id):
            return
        c=storage.get_camera(row["camera_id"])
        options=json.loads(row["options"])
        c.update(options.get("configuration",{}))
        if options.get("feed_type"):
            c["feed_type"]=options["feed_type"]
        mode=options.get("mode","video" if c["kind"]=="video" else "snapshot")
        tracker=Tracker(c["gate"])
        detector.load()
        stats=[]
        confidences=[]
        fingerprint=None
        stale=0
        source_age=None
        source_modified=None
        interval=options.get("interval",5)
        duration=options.get("duration",30)
        fps=None
        headers={}
        if mode=="video" and feed_type(c)=="mjpeg":
            started=time.monotonic()
            sampled_at=-1
            observed=0
            for media in jpeg_frames(c["stream_url"],lambda: cancelled(run_id),duration=duration):
                elapsed=time.monotonic()-started
                if elapsed-sampled_at<1/8:
                    continue
                frame=cv2.imdecode(np.frombuffer(media,np.uint8),cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                sampled_at=elapsed
                detections=detector.detect(frame,c["confidence"],c["roi"])
                crossings=tracker.update(detections,elapsed)
                add_sample(run_id,elapsed,detections,crossings,c["roi"],stats,confidences)
                observed=elapsed
                if len(stats)%8==1:
                    save_frame(run_id,frame,detections)
                    storage.update_run(run_id,progress=min(.98,elapsed/duration))
            if stats:
                save_frame(run_id,frame,detections)
        elif mode=="video":
            if not c.get("stream_url"):
                raise ValueError("This camera provides still images. Select snapshot analysis.")
            if feed_type(c)=="hls":
                storage.update_run(run_id,progress=.03)
                video_path,headers=contexts.enter_context(recorded_hls(c,duration,lambda: cancelled(run_id)))
            else:
                media,headers=download(c["stream_url"],limit=80_000_000,timeout=60)
                check_recent(headers)
                fingerprint=hashlib.sha256(media).hexdigest()
                with storage.connect() as con:
                    previous=con.execute("SELECT id FROM runs WHERE camera_id=? AND status='completed' AND source_hash=? AND created_at>? LIMIT 1",
                                         (c["id"],fingerprint,(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat())).fetchone()
                if previous:
                    storage.update_run(run_id,status="skipped",source_hash=fingerprint,finished_at=storage.now(),progress=1,error="This camera clip has already been analyzed. Wait for the provider to publish a new clip.")
                    return
                fd=tempfile.NamedTemporaryFile(suffix=".mp4",delete=False)
                fd.write(media)
                fd.close()
                temp=Path(fd.name)
                video_path=temp
            cap=cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError("The public video could not be decoded.")
            fps=cap.get(cv2.CAP_PROP_FPS)
            total_frames=cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if not np.isfinite(fps) or fps<=0 or not np.isfinite(total_frames) or total_frames<=0:
                raise ValueError("The clip has no reliable frame timestamps; vehicle flow cannot be measured.")
            observed=min(duration,total_frames/fps)
            step=max(1,round(fps/8))
            frame_number=0
            while frame_number/fps<observed:
                if cancelled(run_id):
                    return
                ok,frame=cap.read()
                if not ok:
                    break
                if frame_number%step==0:
                    elapsed=frame_number/fps
                    detections=detector.detect(frame,c["confidence"],c["roi"])
                    crossings=tracker.update(detections,elapsed)
                    add_sample(run_id,elapsed,detections,crossings,c["roi"],stats,confidences)
                    sampled_frame=frame
                    if len(stats)%8==1:
                        save_frame(run_id,frame,detections)
                        storage.update_run(run_id,progress=min(0.98,elapsed/observed))
                frame_number+=1
            observed=min(observed,frame_number/fps)
            if stats:
                save_frame(run_id,sampled_frame,detections)
        else:
            started=time.monotonic()
            last_hash=None
            observed=0
            headers={}
            while True:
                if cancelled(run_id):
                    return
                from .providers import snapshot_url
                media,headers=download(snapshot_url(c),limit=15_000_000,timeout=25)
                fingerprint=hashlib.sha256(media).hexdigest()
                elapsed=time.monotonic()-started
                if last_hash==fingerprint:
                    stale+=1
                else:
                    frame=cv2.imdecode(np.frombuffer(media,np.uint8),cv2.IMREAD_COLOR)
                    if frame is None:
                        raise ValueError("The camera returned no decodable image. Use a direct JPEG or PNG URL.")
                    detections=detector.detect(frame,c["confidence"],c["roi"])
                    add_sample(run_id,elapsed,detections,0,c["roi"],stats,confidences)
                    save_frame(run_id,frame,detections)
                last_hash=fingerprint
                observed=elapsed
                storage.update_run(run_id,progress=min(0.98,elapsed/max(duration,1)))
                if elapsed>=duration or duration==0:
                    break
                wait=min(interval,max(0,duration-(time.monotonic()-started)))
                until=time.monotonic()+wait
                while time.monotonic()<until:
                    if cancelled(run_id):
                        return
                    time.sleep(min(0.3,max(0,until-time.monotonic())))
        if not stats:
            raise ValueError("No frames were decoded from this camera.")
        try:
            source_modified=parsedate_to_datetime(headers["last-modified"]).isoformat()
            source_age=max(0,(datetime.now(timezone.utc)-parsedate_to_datetime(headers["last-modified"])).total_seconds())
        except (KeyError,ValueError,TypeError):
            pass
        counts={v:round(float(np.mean([s["counts"][v] for s in stats])),2) for v in VEHICLES.values()}
        metrics={"mode":mode,"visible_mean":round(float(np.mean([s["visible"] for s in stats])),2),"visible_peak":max(s["visible"] for s in stats),
                 "occupancy_mean":round(float(np.mean([s["occupancy"] for s in stats])),2),"crossings":tracker.total if mode=="video" else None,
                 "flow_per_second":round(tracker.total/observed,4) if mode=="video" and observed>0 else None,
                 "flow_per_minute":round(tracker.total/observed*60,2) if mode=="video" and observed>0 else None,
                 "duration":round(observed,2),"frames":len(stats),"sampling_fps":round(len(stats)/observed,2) if mode=="video" and observed else None,
                 "class_counts":tracker.classes if mode=="video" else counts,"direction":tracker.direction if mode=="video" else None,
                 "confidence_mean":round(float(np.mean(confidences)),3) if confidences else None,
                 "unchanged_samples":stale,"source_age_seconds":round(source_age) if source_age is not None else None,"source_modified":source_modified,
                 "feed_type":feed_type(c),
                 "note":("Flow describes this recorded live window; it is not a continuous hourly total." if feed_type(c) in ("hls","mjpeg") else "Flow describes this sampled clip; it is not a continuous hourly total.") if mode=="video" else "Stills measure visible vehicles and bounding-box coverage; no vehicle flow or speed is inferred."}
        if not cancelled(run_id):
            storage.update_run(run_id,status="completed",metrics=metrics,source_hash=fingerprint,progress=1,finished_at=storage.now())
    except Exception as exc:
        log.exception("Analysis %s failed",run_id)
        if not cancelled(run_id):
            storage.update_run(run_id,status="failed",error=str(exc)[:600],finished_at=storage.now())
    finally:
        if cap:
            cap.release()
        if temp:
            temp.unlink(missing_ok=True)
        contexts.close()


def add_sample(run_id,elapsed,detections,crossings,roi,stats,confidences):
    counts={v:sum(d["class"]==v for d in detections) for v in VEHICLES.values()}
    stat={"elapsed":round(elapsed,4),"visible":len(detections),"occupancy":round(occupancy(detections,roi),3),"crossings":crossings,"counts":counts}
    stats.append(stat)
    confidences.extend(d["confidence"] for d in detections)
    with storage.connect() as con:
        con.execute("INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?)",(run_id,stat["elapsed"],stat["visible"],stat["occupancy"],crossings,json.dumps(counts)))


class Service:
    def __init__(self):
        self.stop=threading.Event()
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix="vision")
        self.thread=None
        self.bootstrap_errors=[]

    def start(self):
        self.thread=threading.Thread(target=self.loop,daemon=True,name="dispatcher")
        self.thread.start()
        self.bootstrap_thread=threading.Thread(target=self.bootstrap,daemon=True,name="camera-directories")
        self.bootstrap_thread.start()

    def bootstrap(self):
        from .providers import refresh_directories
        with storage.connect() as con:
            count=con.execute("SELECT COUNT(*) FROM cameras").fetchone()[0]
        try:
            detector.load()
        except Exception:
            log.exception("Model load failed")
        self.bootstrap_errors=refresh_directories(self.stop)
        if not count:
            with storage.connect() as con:
                rows=con.execute("SELECT id,data FROM cameras").fetchall()
                chosen=[]
                # Save recognizable London corridors and two Finland cameras.
                for term in ("Tower Bridge","Westminster","Marylebone","Victoria Embankment"):
                    match=next((r for r in rows if term.lower() in json.loads(r["data"])["name"].lower()),None)
                    if match:
                        chosen.append(match["id"])
                chosen.extend(r["id"] for r in rows if r["id"].startswith("fi-") and len(chosen)<6)
                if not chosen:
                    chosen=[r["id"] for r in rows[:4]]
                for camera_id in chosen:
                    con.execute("UPDATE cameras SET saved=1 WHERE id=?",(camera_id,))
        while not self.stop.wait(300):
            self.bootstrap_errors=refresh_directories(self.stop)

    def tick_schedules(self,now=None):
        now=now or datetime.now(timezone.utc)
        with storage.connect() as con:
            rows=con.execute("SELECT * FROM schedules").fetchall()
        for row in rows:
            schedule=json.loads(row["data"])
            if schedule["enabled"]:
                slot=due_slot(schedule,now)
                if slot:
                    enqueue(row["camera_id"],schedule["options"],row["id"],slot)

    def loop(self):
        last_schedule=0
        while not self.stop.is_set():
            try:
                if time.monotonic()-last_schedule>15:
                    self.tick_schedules()
                    last_schedule=time.monotonic()
                with storage.connect() as con:
                    con.execute("BEGIN IMMEDIATE")
                    active=con.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0]
                    queued=con.execute("SELECT id FROM runs WHERE status='queued' ORDER BY created_at LIMIT ?",(max(0,2-active),)).fetchall()
                    for row in queued:
                        con.execute("UPDATE runs SET status='running',started_at=? WHERE id=?",(storage.now(),row[0]))
                for row in queued:
                    self.pool.submit(analyze,row[0])
            except Exception:
                log.exception("Dispatcher failed")
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        with storage.connect() as con:
            con.execute("UPDATE runs SET status='cancelled',finished_at=? WHERE status IN ('queued','running')",(storage.now(),))
        if self.thread:
            self.thread.join(timeout=3)
        self.pool.shutdown(wait=True,cancel_futures=True)


service=Service()
