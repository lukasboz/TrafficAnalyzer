"""Public directory registry, durable refresh status, and rotating image URLs."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import storage
from .camera_sources import ADAPTERS, caltrans_district, estonia_images, singapore_images


def provider(key, name, region, url, description, attribution, kind="snapshot"):
    return {"id": key, "name": name, "region": region, "kind": kind, "url": url,
            "description": description, "attribution": attribution}


PROVIDERS = [
    provider("tfl", "Transport for London", "London, United Kingdom", "https://tfl.gov.uk/info-for/open-data-users/",
             "Short, periodically refreshed camera clips. Flow is measured within each clip.", "Powered by TfL Open Data", "video"),
    provider("digitraffic", "Fintraffic Digitraffic", "Finland", "https://www.digitraffic.fi/en/road-traffic/",
             "Every collected road-weather camera view, including additional directions at each station.", "Fintraffic / digitraffic.fi · CC BY 4.0"),
    provider("drivebc", "DriveBC", "British Columbia, Canada", "https://catalogue.data.gov.bc.ca/dataset/bc-highwaycams",
             "Public highway camera views throughout British Columbia.", "DriveBC · Open Government Licence – British Columbia"),
    provider("calgary", "City of Calgary", "Calgary, Canada", "https://data.calgary.ca/Transportation-Transit/Traffic-Cameras/k7p9-kppz",
             "Municipal traffic camera snapshots.", "City of Calgary · Open Government Licence – City of Calgary"),
    provider("caltrans", "Caltrans", "California, United States", "https://cwwp2.dot.ca.gov/documentation/cctv/cctv.htm",
             "Live HLS video where published, plus public images from all twelve highway districts.", "Caltrans", "video"),
    provider("austin", "Austin Transportation", "Austin, United States", "https://data.austintexas.gov/Transportation-and-Mobility/Traffic-Cameras/b4k4-adkb",
             "Public cameras marked operational by the city.", "City of Austin, Texas"),
    provider("norway", "Statens vegvesen", "Norway", "https://dataut.vegvesen.no/",
             "Live HLS video where published, plus road-camera images from Norway's national road authority.", "Statens vegvesen", "video"),
    provider("iceland", "Vegagerðin", "Iceland", "https://www.vegagerdin.is/vegagerdin/gagnasafn/vefthjonustur/vefmyndavelar",
             "Road-condition camera views, including every published direction.", "Vegagerðin – Icelandic Road and Coastal Administration"),
    provider("estonia", "Transpordiamet / Tarktee", "Estonia", "https://tarktee.transpordiamet.ee/",
             "Road-weather cameras with automatically refreshed capture URLs.", "Transpordiamet / Tarktee"),
    provider("hongkong", "Hong Kong Transport Department", "Hong Kong", "https://data.gov.hk/en-data/dataset/hk-td-tis_2-traffic-snapshot-images",
             "Public traffic snapshots and official camera locations.", "Hong Kong Transport Department / DATA.GOV.HK"),
    provider("singapore", "Singapore Land Transport Authority", "Singapore", "https://data.gov.sg/datasets/d_6cdb6b405b25aaaacbaf7689bcc6fae0/view",
             "Every currently published traffic image. Capture URLs refresh automatically, at most once a minute.", "Land Transport Authority / data.gov.sg · Singapore Open Data Licence"),
    provider("taiwan", "Taiwan Highway Bureau", "Taiwan", "https://cctv-maintain.thb.gov.tw/opendataCCTVs.xml",
             "Continuous public MJPEG video and still images from provincial highway cameras.", "Taiwan Highway Bureau · Government Data Open Licence", "video"),
    provider("nsw", "Live Traffic NSW", "New South Wales, Australia", "https://opendata.transport.nsw.gov.au/",
             "Public road-camera images throughout New South Wales.", "Live Traffic NSW – Transport for NSW · CC BY 4.0"),
    provider("queensland", "QLDTraffic", "Queensland, Australia", "https://queensland.opendatasoft.com/explore/dataset/live-traffic-cameras-gold-coast/",
             "Public Queensland road-camera snapshots published through the open-data portal.", "State of Queensland (Transport and Main Roads) · CC BY 4.0"),
    provider("nzta", "NZ Transport Agency Waka Kotahi", "New Zealand", "https://www.journeys.nzta.govt.nz/traffic-cameras/",
             "Public state-highway cameras marked online and outside maintenance.", "NZ Transport Agency Waka Kotahi"),
    provider("saopaulo", "CET São Paulo", "São Paulo, Brazil", "https://cetsp.com.br/consultas/cameras-cet.aspx",
             "Public municipal traffic snapshots. Street locations are published without map coordinates.", "CET – Companhia de Engenharia de Tráfego, São Paulo"),
    provider("custom", "Any public camera", "Worldwide", "", "Add a public HLS or MJPEG stream, a recent MP4 clip, or a JPEG/PNG image.", "Public camera source", "custom"),
]

DIRECTORY_IDS = tuple(p["id"] for p in PROVIDERS if p["id"] != "custom")
_locks = {key: threading.Lock() for key in DIRECTORY_IDS}
_image_lock = threading.Lock()
_image_cache = {}


def import_provider(provider_id):
    if provider_id not in _locks:
        raise ValueError("Unknown public camera directory.")
    with _locks[provider_id]:
        storage.provider_status(provider_id, refreshing=True, error=None)
        warnings = []
        try:
            if provider_id == "caltrans":
                items = []
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(lambda d=d: list(caltrans_district(d))): d for d in range(1, 13)}
                    for future in as_completed(futures):
                        try:
                            items.extend(future.result())
                        except Exception as exc:
                            warnings.append(f"District {futures[future]}: {str(exc)[:150]}")
            else:
                items = list(ADAPTERS[provider_id]())
            items = list({c["id"]: c for c in items if c}.values())
            if not items:
                raise ValueError("The directory returned no usable public camera images; existing cameras were retained.")
            info = next(p for p in PROVIDERS if p["id"] == provider_id)
            for c in items:
                c["attribution"] = info["attribution"] + (f" · {c['partner_credit']}" if c.get("partner_credit") else "")
            storage.put_cameras(items)
            storage.provider_status(provider_id, refreshing=False, error="; ".join(warnings) or None, last_updated=storage.now())
            return len(items)
        except Exception as exc:
            storage.provider_status(provider_id, refreshing=False, error=str(exc)[:500])
            raise


def refresh_directories(stop=None, force=False):
    """Import new directories on existing installations; retry failures after 30 minutes."""
    from datetime import datetime, timezone
    statuses = storage.provider_statuses()
    with storage.connect() as con:
        upgrades = {r[0] for r in con.execute("SELECT DISTINCT json_extract(data,'$.provider') FROM cameras WHERE json_extract(data,'$.feed_type') IS NULL AND json_extract(data,'$.provider') IN ('caltrans','norway','taiwan')")}
    now = datetime.now(timezone.utc)
    due = []
    for key in DIRECTORY_IDS:
        state = statuses.get(key, {})
        updated = state.get("last_attempt")
        age = (now - datetime.fromisoformat(updated)).total_seconds() if updated else float("inf")
        interval = 1800 if state.get("error") else 21600
        if force or key in upgrades or age >= interval:
            due.append(key)
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        def refresh_one(key):
            if stop is None or not stop.is_set():
                return import_provider(key)
        futures = {pool.submit(refresh_one, key): key for key in due}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors.append(f"{futures[future]}: {str(exc)[:200]}")
    return errors


def snapshot_url(camera):
    """Resolve ephemeral URLs once per minute, shared by previews, analyses, and images."""
    key = camera.get("provider")
    if key not in ("singapore", "estonia"):
        return camera["source_url"]
    with _image_lock:
        cached = _image_cache.get(key)
        if cached is None or time.monotonic() - cached[0] >= 60:
            images = singapore_images() if key == "singapore" else estonia_images()
            cached = (time.monotonic(), images)
            _image_cache[key] = cached
        current = cached[1].get(camera["source_camera_id"])
    if not current:
        raise ValueError("The provider is not currently publishing an image for this camera.")
    return current["image"] if key == "singapore" else current
