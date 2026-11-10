import pytest

from backend import camera_sources as sources, providers, storage
from backend.app import cameras


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    storage.init()
    return tmp_path


def sample(provider="drivebc", key="1"):
    return sources.camera(provider, key, "Road camera", "City", "Canada", 49.2, -123.1,
                          "America/Vancouver", "https://www.drivebc.ca/images/1.jpg")


def test_finland_imports_every_collected_view_and_preserves_original_station_id(monkeypatch):
    payload = {"features": [{"geometry": {"coordinates": [24.9, 60.2]}, "properties": {
        "id": "C01503", "name": "Helsinki", "collectionStatus": "GATHERING", "presets": [
            {"id": "C0150301", "inCollection": True}, {"id": "C0150302", "inCollection": True},
            {"id": "C0150303", "inCollection": False}]}}]}
    monkeypatch.setattr(sources, "fetch_json", lambda _: payload)
    items = list(sources.digitraffic())
    assert [c["id"] for c in items] == ["fi-C01503", "fi-C01503-C0150302"]
    assert items[1]["source_url"].endswith("C0150302.jpg")


def test_hong_kong_handles_the_published_double_bom_and_tab_delimited_utf16(monkeypatch):
    payload = ("\ufeffkey\tregion\tdistrict\tdescription\tlatitude\tlongitude\turl\r\n"
               "H429F\tHong Kong Island\tSouthern\tAberdeen Praya Road\t22.24845\t114.1505\thttps://tdcctv.data.one.gov.hk/H429F.JPG\r\n").encode("utf-16")
    monkeypatch.setattr(sources, "download", lambda *a, **k: (payload, {}))
    camera = next(sources.hongkong())
    assert camera["id"] == "hongkong-H429F"
    assert camera["lat"] == 22.24845 and camera["timezone"] == "Asia/Hong_Kong"


def test_taiwan_preserves_the_continuous_mjpeg_video_and_snapshot(monkeypatch):
    from xml.etree import ElementTree as ET
    payload = ET.fromstring('''<CCTVList xmlns="http://traffic.transportdata.tw/standard/traffic/schema/">
      <CCTVs><CCTV><CCTVID>CCTV-14-0620-009-002</CCTVID><RoadName>台62線</RoadName>
      <SurveillanceDescription>台62線西向</SurveillanceDescription><PositionLon>121.7321</PositionLon>
      <PositionLat>25.10529</PositionLat><VideoImageURL>https://cctv-ss02.thb.gov.tw:443/T62-9K+020/snapshot</VideoImageURL>
      <VideoStreamURL>https://cctv-ss02.thb.gov.tw:443/T62-9K+020</VideoStreamURL></CCTV></CCTVs></CCTVList>''')
    monkeypatch.setattr(sources, "fetch_xml", lambda _: payload)
    camera = next(sources.taiwan())
    assert camera["name"] == "台62線西向"
    assert camera["kind"] == "video" and camera["feed_type"] == "mjpeg"
    assert camera["stream_url"] == "https://cctv-ss02.thb.gov.tw:443/T62-9K+020"


def test_caltrans_ids_survive_reordering_and_offline_cameras_are_excluded(monkeypatch):
    def record(index, active="true"):
        return {"cctv": {"index": index, "inService": active, "location": {
            "locationName": "Hwy 5 at Pocket", "latitude": "38.481128", "longitude": "-121.510528"},
            "imageData": {"static": {"currentImageURL": "https://cwwp2.dot.ca.gov/data/d3/cctv/image/hwy5atpocket/hwy5atpocket.jpg"},
                          "streamingVideoURL": "https://wzmedia.dot.ca.gov/D3/camera/playlist.m3u8"}}}
    monkeypatch.setattr(sources, "fetch_json", lambda _: {"data": [record("1"), record("2", "false")]})
    first = list(sources.caltrans_district(3))
    monkeypatch.setattr(sources, "fetch_json", lambda _: {"data": [record("999")]})
    assert len(first) == 1 and first[0]["id"] == next(sources.caltrans_district(3))["id"]
    assert first[0]["kind"] == "video" and first[0]["feed_type"] == "hls"


def test_socrata_catalog_pages_until_exhausted(monkeypatch):
    requests = []
    def fetch(url):
        requests.append(url)
        return list(range(1000)) if "$offset=0" in url else [1001]
    monkeypatch.setattr(sources, "fetch_json", fetch)
    assert len(list(sources.socrata_records("https://data.calgary.ca/resource/k7p9-kppz.json"))) == 1001
    assert "$offset=1000" in requests[1]


def test_saopaulo_keeps_unlocated_cameras_without_inventing_coordinates(monkeypatch):
    payload = b"gCams.push({pasta:225,titulo:'Ascendino Reis',subTitulo:'R Pedro de Toledo',detalhe:'',ativa:true,apImg:1});gCams.push({pasta:22,titulo:'Offline',subTitulo:'',detalhe:'',ativa:false});"
    monkeypatch.setattr(sources, "download", lambda *a, **k: (payload, {}))
    items = list(sources.saopaulo())
    assert len(items) == 1 and items[0]["id"] == "saopaulo-225"
    assert items[0]["lat"] is None and items[0]["lon"] is None
    assert items[0]["source_url"] == "https://cameras.cetsp.com.br/Cams/225/1.jpg"


def test_nzta_excludes_maintenance_and_offline_views(monkeypatch):
    base = {"geometry": {"coordinates": [172.61162, -43.449229]}, "properties": {
        "id": 1430, "Name": "SH1 WBB Groynes Dr South", "ImageUrl": "https://www.trafficnz.info/camera/706.jpg",
        "Offline": 0, "UnderMaintenance": 0}}
    monkeypatch.setattr(sources, "fetch_json", lambda _: {"features": [base,
        {**base, "properties": {**base["properties"], "Offline": 1}},
        {**base, "properties": {**base["properties"], "UnderMaintenance": 1}}]})
    assert [c["id"] for c in sources.nzta()] == ["nzta-1430"]


def test_import_is_idempotent_and_preserves_saved_geometry_and_timezone(database, monkeypatch):
    old = sample()
    old.update(gate=[.1, .2, .8, .2], confidence=.7, timezone="America/Toronto")
    storage.put_cameras([old])
    with storage.connect() as con:
        con.execute("UPDATE cameras SET saved=1")
    monkeypatch.setitem(sources.ADAPTERS, "drivebc", lambda: iter([sample(), sample()]))
    assert providers.import_provider("drivebc") == 1
    current = storage.get_camera(old["id"])
    assert current["saved"] and current["gate"] == old["gate"] and current["confidence"] == .7
    assert current["timezone"] == "America/Toronto" and "DriveBC" in current["attribution"]


def test_failed_refresh_retains_cameras_and_success_timestamp(database, monkeypatch):
    storage.put_cameras([sample()])
    storage.provider_status("drivebc", last_updated="2026-01-01T00:00:00+00:00")
    monkeypatch.setitem(sources.ADAPTERS, "drivebc", lambda: iter([]))
    with pytest.raises(ValueError, match="retained"):
        providers.import_provider("drivebc")
    assert storage.get_camera("drivebc-1") is not None
    status = storage.provider_statuses()["drivebc"]
    assert not status["refreshing"] and status["error"]
    assert status["last_updated"] == "2026-01-01T00:00:00+00:00"


def test_existing_database_gets_new_directories_and_does_not_refetch_fresh_sources(database, monkeypatch):
    storage.put_cameras([sample()])
    storage.provider_status("drivebc", last_attempt=storage.now(), error=None)
    imported = []
    monkeypatch.setattr(providers, "import_provider", lambda key: imported.append(key))
    providers.refresh_directories()
    assert set(imported) == set(providers.DIRECTORY_IDS) - {"drivebc"}


def test_rotating_urls_share_one_minute_cache_and_do_not_serve_withdrawn_images(monkeypatch):
    clock = [0]
    calls = []
    monkeypatch.setattr(providers.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(providers, "_image_cache", {})
    def images():
        calls.append(clock[0])
        return {"2701": {"image": f"https://images.data.gov.sg/frame-{clock[0]}.jpg"}}
    monkeypatch.setattr(providers, "singapore_images", images)
    camera = {"provider": "singapore", "source_camera_id": "2701", "source_url": "https://images.data.gov.sg/old.jpg"}
    assert providers.snapshot_url(camera).endswith("frame-0.jpg")
    clock[0] = 59
    assert providers.snapshot_url(camera).endswith("frame-0.jpg")
    clock[0] = 60
    assert providers.snapshot_url(camera).endswith("frame-60.jpg") and len(calls) == 2
    with pytest.raises(ValueError, match="not currently publishing"):
        providers.snapshot_url({**camera, "source_camera_id": "missing"})


def test_camera_api_can_retrieve_every_record_beyond_the_original_limit(database):
    storage.put_cameras([{**sample(key=str(i)), "name": "Same camera name"} for i in range(4105)])
    first = cameras(limit=4000, offset=0)
    second = cameras(limit=4000, offset=4000)
    ids = [c["id"] for c in first["items"] + second["items"]]
    assert first["total"] == 4105 and len(ids) == len(set(ids)) == 4105


def test_nsw_image_headers_keep_identity_and_redirects_are_revalidated(monkeypatch):
    import httpx
    from backend import network
    requests, validated = [], []
    def handle(request):
        requests.append(request)
        if request.url.host == "webcams.transport.nsw.gov.au":
            return httpx.Response(302, headers={"location": "https://other.example/camera.jpg"})
        return httpx.Response(200, content=b"image")
    client_type = httpx.Client
    monkeypatch.setattr(network, "validate_url", lambda url: validated.append(url))
    monkeypatch.setattr(network.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs))
    payload, _ = network.download("https://webcams.transport.nsw.gov.au/camera.jpeg")
    assert payload == b"image" and len(validated) == 2
    assert "Mozilla" in requests[0].headers["user-agent"] and "Flowstate" in requests[0].headers["user-agent"]
    assert requests[1].headers["user-agent"] == network.HEADERS["User-Agent"]
