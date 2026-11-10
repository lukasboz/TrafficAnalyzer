"""Adapters for intentionally published, keyless traffic-camera directories."""
import csv
import hashlib
import html
import io
import json
import math
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from .network import download

SINGAPORE_URL = "https://api.data.gov.sg/v1/transport/traffic-images"
ESTONIA_IMAGES_URL = "https://tarktee.transpordiamet.ee/api/v1/datex/roadCameraImages"


def public_media_url(url):
    """DNS and redirects are checked by every media download."""
    try:
        p = urlsplit(url)
        return bool(p.scheme in ("http", "https") and p.hostname and not p.username
                    and not p.password and p.port in (None, 80, 443))
    except (TypeError, ValueError):
        return False


def camera(provider, key, name, city, country, lat, lon, zone, source, video=None, **extra):
    if lat is not None or lon is not None:
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return None
    if not public_media_url(source):
        return None
    feed_type = extra.pop("feed_type", None)
    if public_media_url(video):
        path = urlsplit(video).path.lower()
        feed_type = feed_type or ("hls" if path.endswith(".m3u8") else "clip" if path.endswith(".mp4") else None)
    if feed_type not in ("hls", "clip", "mjpeg") or not public_media_url(video):
        video, feed_type = None, "snapshot"
    return {"id": f"{provider}-{key}", "name": html.unescape(str(name)), "city": html.unescape(str(city or country)),
            "country": country, "lat": lat, "lon": lon, "timezone": zone, "provider": provider,
            "source_url": source, "stream_url": video, "kind": "video" if video else "snapshot", "feed_type": feed_type,
            "gate": [0.15, 0.6, 0.85, 0.6], "roi": [0, 0, 1, 1], "confidence": 0.3, **extra}


def stable_key(url):
    return hashlib.sha256(urlsplit(url).path.encode()).hexdigest()[:20]


def fetch_json(url):
    payload, _ = download(url, limit=25_000_000, timeout=25, accept="application/json")
    return json.loads(payload)


def fetch_xml(url):
    payload, _ = download(url, limit=15_000_000, timeout=25, accept="application/xml")
    return ET.fromstring(payload)


def socrata_records(url):
    offset = 0
    while True:
        rows = fetch_json(f"{url}?$limit=1000&$offset={offset}&$order=:id")
        yield from rows
        if len(rows) < 1000:
            break
        offset += len(rows)


def text(node, tag):
    return node.findtext(f".//{{*}}{tag}")


def tfl():
    for c in fetch_json("https://api.tfl.gov.uk/Place/Type/JamCam"):
        props = {p["key"]: p["value"] for p in c.get("additionalProperties", [])}
        if props.get("available") == "true":
            yield camera("tfl", c["id"], c["commonName"], "London", "United Kingdom", c["lat"], c["lon"],
                         "Europe/London", props.get("imageUrl"), props.get("videoUrl"))


def digitraffic():
    for c in fetch_json("https://tie.digitraffic.fi/api/weathercam/v1/stations")["features"]:
        p = c["properties"]
        if p.get("collectionStatus") not in (None, "GATHERING"):
            continue
        lon, lat = c["geometry"]["coordinates"][:2]
        presets = [s for s in p.get("presets", []) if s.get("inCollection", True)]
        for i, preset in enumerate(presets):
            item = camera("digitraffic", p["id"] if i == 0 else f"{p['id']}-{preset['id']}",
                          (p.get("nameEn") or p.get("name") or str(p["id"])) + (f" · {preset.get('presentationName') or preset['id']}" if i else ""),
                          p.get("municipality"), "Finland", lat, lon, "Europe/Helsinki",
                          preset.get("imageUrl") or f"https://weathercam.digitraffic.fi/{preset['id']}.jpg")
            if item:
                item["id"] = "fi-" + str(p["id"]) + (f"-{preset['id']}" if i else "")
            yield item


def drivebc():
    for c in fetch_json("https://www.drivebc.ca/api/webcams/"):
        if not c.get("is_on", True) or not c.get("should_appear", True):
            continue
        lon, lat = c["location"]["coordinates"][:2]
        yield camera("drivebc", c["id"], c.get("name_override") or c["name"], c.get("region_name"), "Canada",
                     lat, lon, "America/Vancouver", f"https://www.drivebc.ca/images/{c['id']}.jpg", partner_credit=c.get("credit", ""))


def calgary():
    for c in socrata_records("https://data.calgary.ca/resource/k7p9-kppz.json"):
        source = c.get("camera_url", {}).get("url", "").replace("http://", "https://", 1)
        lon, lat = c.get("point", {}).get("coordinates", [None, None])[:2]
        yield camera("calgary", stable_key(source), c.get("camera_location", "Calgary traffic camera"),
                     "Calgary", "Canada", lat, lon, "America/Edmonton", source)


def austin():
    for c in socrata_records("https://data.austintexas.gov/resource/b4k4-adkb.json"):
        if c.get("camera_status") != "TURNED_ON":
            continue
        lon, lat = c.get("location", {}).get("coordinates", [None, None])[:2]
        yield camera("austin", c["camera_id"], c["location_name"].strip(), "Austin", "United States",
                     lat, lon, "America/Chicago", c.get("screenshot_address"))


def caltrans_district(district):
    records = fetch_json(f"https://cwwp2.dot.ca.gov/data/d{district}/cctv/cctvStatusD{district:02}.json")["data"]
    for record in records:
        c = record["cctv"]
        if str(c.get("inService", "true")).lower() != "true":
            continue
        loc = c["location"]
        source = c.get("imageData", {}).get("static", {}).get("currentImageURL")
        if source:
            yield camera("caltrans", f"d{district}-{stable_key(source)}", loc["locationName"], loc.get("nearbyPlace") or loc.get("county"),
                         "United States", loc.get("latitude"), loc.get("longitude"), "America/Los_Angeles", source,
                         c.get("imageData", {}).get("streamingVideoURL"))


def norway():
    url = "https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1%3ACctvSimple/items?f=application%2Fjson&limit=2000"
    while url:
        payload = fetch_json(url)
        for c in payload["features"]:
            p = c["properties"]
            if p.get("status.stillImageAvailability") not in (None, "videoOrImagesAvailable"):
                continue
            lon, lat = c["geometry"]["coordinates"][:2]
            yield camera("norway", p["cameraId"], f"{p.get('description', p['cameraId'])} · {p.get('orientationDescription', '')}".rstrip(" ·"),
                         p.get("roadNumber"), "Norway", lat, lon, "Europe/Oslo", p.get("stillImageUrl"), p.get("videoUrl"))
        next_link = next((link["href"] for link in payload.get("links", []) if link.get("rel") == "next"), None)
        url = urljoin(url, next_link) if next_link else None


def iceland():
    for c in fetch_json("https://gagnaveita.vegagerdin.is/api/vefmyndavelar2014_1"):
        source = c.get("Slod", "")
        yield camera("iceland", stable_key(source), c.get("Skyring") or c["Myndavel"], c.get("Vegheiti"), "Iceland",
                     c.get("Breidd"), c.get("Lengd"), "Atlantic/Reykjavik", source)


def hongkong():
    payload, _ = download("https://static.data.gov.hk/td/traffic-snapshot-images/code/Traffic_Camera_Locations_En.csv", limit=3_000_000)
    encoding = "utf-16" if payload[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    content = payload.decode(encoding).lstrip("\ufeff")
    delimiter = "\t" if "\t" in content.splitlines()[0] else ","
    for c in csv.DictReader(io.StringIO(content), delimiter=delimiter):
        yield camera("hongkong", c["key"], c["description"], c.get("district"), "Hong Kong", c.get("latitude"), c.get("longitude"),
                     "Asia/Hong_Kong", c.get("url"))


def singapore_images():
    payload = fetch_json(SINGAPORE_URL)
    if not payload.get("items"):
        raise ValueError("Singapore is not currently publishing camera images.")
    return {str(c["camera_id"]): c for c in payload["items"][-1]["cameras"]}


def singapore():
    for key, c in singapore_images().items():
        yield camera("singapore", key, f"Singapore traffic camera {key}", "Singapore", "Singapore",
                     c["location"]["latitude"], c["location"]["longitude"], "Asia/Singapore", c["image"], source_camera_id=key)


def nsw():
    for c in fetch_json("https://data.livetraffic.com/cameras/traffic-cam.json")["features"]:
        p = c["properties"]
        lon, lat = c["geometry"]["coordinates"][:2]
        yield camera("nsw", c["id"], p["title"], p.get("region", "New South Wales").replace("_", " "), "Australia",
                     lat, lon, "Australia/Sydney", p.get("href"))


def queensland():
    url = "https://queensland.opendatasoft.com/api/explore/v2.1/catalog/datasets/live-traffic-cameras-gold-coast/exports/json"
    for c in fetch_json(url):
        loc = c.get("geo_point_2d", {})
        yield camera("queensland", c["id"], c.get("view") or c["title"], c.get("region"), "Australia",
                     loc.get("lat"), loc.get("lon"), "Australia/Brisbane", c.get("href"))


def taiwan():
    root = fetch_xml("https://cctv-maintain.thb.gov.tw/opendataCCTVs.xml")
    for c in root.findall(".//{*}CCTV"):
        key = text(c, "CCTVID")
        yield camera("taiwan", key, text(c, "SurveillanceDescription") or text(c, "RoadName") or key, text(c, "RoadName") or "Provincial highways", "Taiwan",
                     text(c, "PositionLat"), text(c, "PositionLon"), "Asia/Taipei", text(c, "VideoImageURL"),
                     text(c, "VideoStreamURL"), feed_type="mjpeg")


def estonia_images():
    root = fetch_xml(ESTONIA_IMAGES_URL)
    images = {}
    for view in root.findall(".//{*}trafficView"):
        reference = view.find(".//{*}linearPredefinedLocationReference")
        source = text(view, "urlLinkAddress")
        if reference is not None and public_media_url(source):
            images[reference.attrib["id"]] = source
    return images


def estonia():
    root = fetch_xml("https://tarktee.transpordiamet.ee/api/v1/datex/roadCameraLocations")
    images = estonia_images()
    for c in root.findall(".//{*}predefinedLocation"):
        key = c.attrib["id"]
        yield camera("estonia", key, text(c, "value") or key, "Road network", "Estonia", text(c, "latitude"), text(c, "longitude"),
                     "Europe/Tallinn", images.get(key), source_camera_id=key)


def nzta():
    for c in fetch_json("https://www.journeys.nzta.govt.nz/assets/map-data-cache/cameras.json")["features"]:
        p = c["properties"]
        if p.get("Offline") or p.get("UnderMaintenance"):
            continue
        lon, lat = c["geometry"]["coordinates"][:2]
        yield camera("nzta", p["id"], p["Name"], "State highways", "New Zealand", lat, lon,
                     "Pacific/Auckland", p.get("ImageUrl"))


def saopaulo():
    payload, _ = download("https://cameras.cetsp.com.br/View/Cam.aspx", limit=2_000_000, timeout=25)
    # Parse the published camera declarations without executing provider JavaScript.
    pattern = r"gCams\.push\(\{pasta:(\d+),titulo:'([^']*)',subTitulo:'([^']*)',detalhe:'([^']*)',ativa:(true|false)"
    for key, title, subtitle, detail, active in re.findall(pattern, payload.decode("utf-8-sig")):
        if active == "true":
            yield camera("saopaulo", key, " / ".join(s for s in (title, subtitle, detail) if s), "São Paulo", "Brazil",
                         None, None, "America/Sao_Paulo", f"https://cameras.cetsp.com.br/Cams/{key}/1.jpg")


ADAPTERS = {"tfl": tfl, "digitraffic": digitraffic, "drivebc": drivebc, "calgary": calgary,
            "austin": austin, "norway": norway, "iceland": iceland, "hongkong": hongkong,
            "singapore": singapore, "nsw": nsw, "queensland": queensland, "taiwan": taiwan, "estonia": estonia,
            "nzta": nzta, "saopaulo": saopaulo}
