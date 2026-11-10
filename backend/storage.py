"""Single-instance durable SQLite storage. Every thread owns its connection."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DATA


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    con = sqlite3.connect(DATA / "flowstate.sqlite3", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init():
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY, data TEXT NOT NULL, saved INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS provider_imports(id TEXT PRIMARY KEY, last_updated TEXT, last_attempt TEXT,
          error TEXT, refreshing INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY, camera_id TEXT NOT NULL REFERENCES cameras(id), data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, camera_id TEXT NOT NULL REFERENCES cameras(id), status TEXT NOT NULL,
          created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, options TEXT NOT NULL, metrics TEXT, error TEXT,
          progress REAL NOT NULL DEFAULT 0, source_hash TEXT, frame TEXT, detections TEXT,
          schedule_id TEXT, slot TEXT, UNIQUE(schedule_id,slot));
        CREATE TABLE IF NOT EXISTS samples(run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          elapsed REAL NOT NULL, visible INTEGER NOT NULL, occupancy REAL NOT NULL, crossings INTEGER NOT NULL,
          counts TEXT NOT NULL, PRIMARY KEY(run_id,elapsed));
        CREATE INDEX IF NOT EXISTS idx_runs_camera_created ON runs(camera_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_camera ON runs(camera_id) WHERE status IN ('queued','running');
        """)
        con.execute("UPDATE provider_imports SET refreshing=0")
        con.execute("UPDATE runs SET status='failed',error='Analysis service restarted during this run.',finished_at=? WHERE status IN ('queued','running')", (now(),))


def camera(row):
    return {**json.loads(row["data"]), "saved": bool(row["saved"])}


def get_camera(camera_id):
    with connect() as con:
        row = con.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
    return camera(row) if row else None


def put_cameras(items):
    with connect() as con:
        for item in items:
            old = con.execute("SELECT data FROM cameras WHERE id=?", (item["id"],)).fetchone()
            if old:
                prior = json.loads(old[0])
                for key in ("gate", "roi", "confidence", "timezone"):
                    if key in prior:
                        item[key] = prior[key]
            con.execute("INSERT INTO cameras(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (item["id"], json.dumps(item)))


def provider_status(provider_id, **fields):
    if fields.get("refreshing"):
        fields["last_attempt"] = now()
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO provider_imports(id) VALUES(?)", (provider_id,))
        con.execute("UPDATE provider_imports SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?", (*fields.values(), provider_id))


def provider_statuses():
    with connect() as con:
        return {row["id"]: {**dict(row), "refreshing": bool(row["refreshing"])}
                for row in con.execute("SELECT * FROM provider_imports")}


def run(row):
    d = dict(row)
    for key in ("options", "metrics", "detections"):
        d[key] = json.loads(d[key]) if d[key] else None
    d["frame_url"] = f"/api/runs/{d['id']}/frame" if d.pop("frame") else None
    return d


def update_run(run_id, **fields):
    for key in ("metrics", "detections"):
        if key in fields:
            fields[key] = json.dumps(fields[key])
    with connect() as con:
        con.execute("UPDATE runs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?", (*fields.values(), run_id))
