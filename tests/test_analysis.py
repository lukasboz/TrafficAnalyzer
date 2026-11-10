import json
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend import storage
from backend.engine import enqueue,due_slot,next_fire
from backend.vision import Tracker,occupancy
from backend.network import validate_url
from backend.app import CameraPatch,RunOptions,ScheduleInput

def detection(x,y,kind="car"):
    return {"box":[x-.04,y-.04,x+.04,y+.04],"class":kind,"confidence":.9}

def test_crossing_counts_once_and_separates_directions():
    tracker=Tracker([0.1,.5,.9,.5])
    assert tracker.update([detection(.3,.43),detection(.7,.57,"truck")],0)==0
    assert tracker.update([detection(.3,.49),detection(.7,.51,"truck")],.125)==0
    assert tracker.update([detection(.3,.55),detection(.7,.45,"truck")],.25)==2
    assert tracker.total==2
    assert tracker.classes["car"]==1 and tracker.classes["truck"]==1
    assert tracker.direction=={"a_to_b":1,"b_to_a":1}
    tracker.update([detection(.3,.44),detection(.7,.56,"truck")],.375)
    assert tracker.total==2

def test_crossing_beyond_segment_is_not_counted():
    tracker=Tracker([.4,.5,.6,.5])
    tracker.update([detection(.2,.45)],0)
    tracker.update([detection(.2,.55)],.125)
    assert tracker.total==0

def test_lost_track_is_not_matched_to_new_vehicle():
    tracker=Tracker([.1,.5,.9,.5])
    tracker.update([detection(.3,.45)],0)
    tracker.update([detection(.3,.55)],3)
    assert tracker.total==0

def test_occupancy_uses_union_and_selected_area():
    boxes=[{"box":[0,0,.5,.5]},{"box":[.25,0,.75,.5]}]
    assert occupancy(boxes,[0,0,1,1])==37.5
    assert occupancy(boxes,[0,0,.5,.5])==100

def schedule(zone="Europe/London",clock="08:00",days=None):
    return {"timezone":zone,"time":clock,"days":days if days is not None else list(range(7))}

def test_schedule_uses_camera_timezone_and_lateness_limit():
    s=schedule("America/Toronto","08:00")
    assert due_slot(s,datetime(2026,10,5,12,0,30,tzinfo=timezone.utc))=="2026-10-05T08:00"
    assert due_slot(s,datetime(2026,10,5,11,59,tzinfo=timezone.utc)) is None
    assert due_slot(s,datetime(2026,10,5,12,10,tzinfo=timezone.utc)) is None

def test_dst_missing_hour_is_skipped_and_fall_hour_runs_once():
    spring=schedule("America/Toronto","02:30")
    assert due_slot(spring,datetime(2026,3,8,7,30,tzinfo=timezone.utc)) is None
    fall=schedule("America/Toronto","01:30")
    assert due_slot(fall,datetime(2026,11,1,5,30,tzinfo=timezone.utc))=="2026-11-01T01:30"
    assert due_slot(fall,datetime(2026,11,1,6,30,tzinfo=timezone.utc)) is None
    assert next_fire(spring,datetime(2026,3,8,0,tzinfo=timezone.utc)).startswith("2026-03-09T02:30")

@pytest.mark.parametrize("url",["http://127.0.0.1/a.jpg","http://[::1]/a","http://169.254.169.254/","file:///etc/passwd","http://10.0.0.1/a","https://user:pass@example.com/a","https://example.com:8080/a"])
def test_private_and_non_http_sources_rejected(url):
    with pytest.raises(ValueError):validate_url(url)

@pytest.mark.parametrize("patch",[{"roi":[0,0,0,1]},{"gate":[.5,.5,.5,.5]},{"roi":[0,0,2,1]},{"confidence":.01},{"timezone":"No/Such_Zone"}])
def test_invalid_camera_configuration_rejected(patch):
    with pytest.raises(ValueError):CameraPatch(**patch)

def test_invalid_analysis_duration_and_schedule_days_rejected():
    with pytest.raises(ValueError):RunOptions(mode="video",duration=0)
    with pytest.raises(ValueError):ScheduleInput(camera_id="x",name="Rush hour",time="08:00",timezone="UTC",days=[7],options=RunOptions())

@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,"DATA",tmp_path)
    storage.init()
    storage.put_cameras([{"id":"test","name":"Test camera","kind":"video","gate":[.1,.5,.9,.5],"roi":[0,0,1,1],"confidence":.3,"source_url":"https://example.com/a.jpg","stream_url":"https://example.com/a.mp4"}])
    return tmp_path

def test_concurrent_requests_share_one_run_and_capture_config(database):
    with ThreadPoolExecutor(max_workers=8) as executor:
        ids=list(executor.map(lambda _:enqueue("test",{"mode":"video","duration":30}),range(16)))
    assert len(set(ids))==1
    with storage.connect() as con:rows=con.execute("SELECT * FROM runs").fetchall()
    assert len(rows)==1
    assert json.loads(rows[0]["options"])["configuration"]["confidence"]==.3

def test_schedule_slot_cannot_be_created_twice(database):
    run_id=enqueue("test",{"mode":"video","duration":30},"morning","2026-10-05T08:00")
    storage.update_run(run_id,status="completed")
    assert enqueue("test",{"mode":"video","duration":30},"morning","2026-10-05T08:00") is None

def test_restart_marks_interrupted_runs_failed(database):
    run_id=enqueue("test",{"mode":"video","duration":30})
    storage.init()
    with storage.connect() as con:row=con.execute("SELECT status,error FROM runs WHERE id=?",(run_id,)).fetchone()
    assert row[0]=="failed" and "restarted" in row[1]

def test_duplicate_clip_is_skipped_without_counting_again(database,monkeypatch):
    import hashlib
    from backend import engine
    media=b"previously analyzed public clip"
    original=enqueue("test",{"mode":"video","duration":30})
    storage.update_run(original,status="completed",source_hash=hashlib.sha256(media).hexdigest())
    duplicate=enqueue("test",{"mode":"video","duration":30})
    monkeypatch.setattr(engine,"download",lambda *a,**k:(media,{}))
    monkeypatch.setattr(engine.detector,"load",lambda:None)
    engine.analyze(duplicate)
    with storage.connect() as con:row=con.execute("SELECT status,metrics,error FROM runs WHERE id=?",(duplicate,)).fetchone()
    assert row[0]=="skipped" and row[1] is None and "already been analyzed" in row[2]
