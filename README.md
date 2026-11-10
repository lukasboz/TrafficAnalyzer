# Flowstate — Traffic observatory

A working web app for measuring traffic from public cameras. Next.js provides the Vercel-ready dashboard; a FastAPI service runs YOLOX Tiny with ONNX Runtime, tracks vehicles, stores observations in SQLite, and dispatches timezone-aware scheduled jobs.

## Run on Windows

Requires Python 3.12 and Node 22.13+ (Node 24 LTS recommended). Live HLS analysis also needs `ffmpeg` on PATH; the Docker image installs it.

```powershell
.\scripts\start.ps1
```

Open **http://localhost:3000**. First launch installs missing dependencies, imports the public camera directories, and downloads the official YOLOX Tiny model. The script starts the dashboard and analysis service in hidden background processes. Logs and a generated service key are in the ignored `.runtime` folder.

```powershell
.\scripts\stop.ps1                 # Stop this app's processes
.\scripts\restart-service.ps1      # Reload backend changes without stopping the dashboard
```

On macOS/Linux, run `bash scripts/start.sh`. The generated PID files identify the two background processes. The launcher is intended for one running instance.

## Use the app

1. Open **Camera explorer**, search for a camera, and select **Open monitor**. The explorer defaults to **Live streams & recent clips**; use the feed filter to show live streams, clips, snapshots, or all feeds. Save cameras with the star.
2. Use the monitor's settings button to draw a counting line across a clear road section. Click two endpoints. Optionally select an analysis area and adjust confidence. Save the configuration.
3. Select **Video flow** to record a live video window or analyze a recent clip, or **Snapshot count** for visible vehicles. Run the analysis. Results update automatically; the service continues when the page closes.
4. Inspect **Detection view**, individual tracked vehicles, observation charts, vehicle classes, and direction counts. **Live video** plays continuous HLS/MJPEG video; **Recent clip** plays each newly published MP4 once. Playback can be newer than an existing analysis.
5. Create morning/evening schedules with a time, weekdays, timezone, observation duration, and camera. Pause or delete schedules from the schedule view.
6. Use **Traffic reports** to compare local hours, filter cameras and dates, inspect past analyses, and export CSV.

Views, selected cameras, historical observations, explorer filters, and report settings are stored in the page URL. Bookmark or share that URL to return to the same view; refresh and browser Back/Forward preserve it. Protected workspace links return to the requested view after sign-in. Explorer **Reset filters** and **Show all cameras** clear all filters, including the default video-only filter.

Charts offer **View measurement data** for a keyboard-accessible table of exact samples or hourly averages. Fractional averages are retained; missing observations are labeled separately from measured zeros. Report camera/period changes clear the previous results while loading, and failed requests offer **Retry report**. Snapshot-only observations explain why vehicle flow is unavailable.

The camera explorer imports published camera views from **16 public directories across 13 countries and territories**: TfL London, Fintraffic Finland (every collected station view), DriveBC and Calgary in Canada, all 12 Caltrans districts and Austin in the United States, Norway, Iceland, Estonia, Hong Kong, Singapore, Taiwan's provincial highways, New South Wales and Queensland in Australia, New Zealand, and CET São Paulo in Brazil. Counts change with provider availability. This is coverage from connected directories, not a complete registry of every publicly accessible camera worldwide.

New directories import automatically into existing installations. Imports refresh every six hours, with failed imports retried after 30 minutes; source management shows progress, the last successful import, and any error. Existing cameras and observations are retained when a provider fails. Singapore and Estonia image URLs are resolved from their latest feeds with a shared one-minute cache. All catalog pages load in the explorer; country/territory and network filters narrow the list and map. Map markers use a canvas renderer and only draw cameras in the current view. São Paulo publishes street descriptions without coordinates, so its cameras appear in the list without invented map positions.

The connected video networks are **Caltrans and Norway (HLS)**, **Taiwan Highway Bureau (continuous MJPEG)**, and **TfL (periodically refreshed MP4 clips)**. Directories that only publish still images remain available through the snapshot/all-feeds filter. Published stream URLs indicate capability; individual cameras can still be offline.

Other locations can be added with a **direct public JPEG/PNG URL**, or a thumbnail image plus an **HLS playlist (.m3u8), continuous MJPEG stream, or recently updated MP4 URL**. Camera webpages, logins and RTSP are not supported. Public availability does not guarantee reuse rights; source credits and documentation are exposed in the app. Imported timezone defaults can be edited for local exceptions.

## Live detection preview

Open a camera monitor and select **Live detection**. No saved analysis is required. The preview shows each detected vehicle with a box, class, confidence, track ID and optional motion trail. The counting line and analysis area use the camera's saved settings. Cars already counted are highlighted in teal. Use **Configure camera analysis** to save a new line, area or confidence; the preview picks up saved changes automatically.

Live HLS/MJPEG previews follow new video frames with detection targeting six frames per second. The monitor displays visible vehicles, directional line crossings for the current session or clip, detection rate, and provider-reported source age where available. Inference and network delays can lower the displayed frame rate. HLS playback shows seconds behind the stream edge, which does not measure capture-to-view latency. **Go live** returns playback to that edge.

London clips are checked for updates every 30 seconds and each new clip plays once, then waits for the next clip. The preview analyzes at most the first 60 seconds. Clips with a provider `Last-Modified` timestamp older than five minutes are rejected in playback, previews, and saved analyses. Missing timestamps are shown explicitly; retrieval time is never presented as capture time. Counters reset for a new clip, stream gap/reconnect, or saved geometry/confidence change.

Live HLS analyses record newly published segments for the selected observation duration before decoding a local recording. MJPEG analyses sample the continuous connection for that duration. HLS previews decode each new segment once; they skip gaps and reset tracking instead of replaying old segments. Source discontinuities can shorten a saved HLS observation. Recording is limited to 80 MB and five minutes. Encrypted, byte-range and fragmented-MP4 HLS analysis is unsupported, while browser playback supports standard HLS media formats. Ended HLS playlists and streams with published program timestamps older than five minutes are rejected.

Still-image cameras are checked every three seconds. Unchanged images reuse their previous detections. New images or saved configuration changes trigger inference. Still previews show boxes and geometry, but do not infer unique track IDs or crossings from sparse images.

**Pause feed** freezes the current frame and releases the preview session. **Resume feed** reconnects. Hidden tabs, changed cameras, and closed monitors stop consuming preview inference; abandoned sessions expire after 15 seconds. Viewers of the same camera share a worker, with a maximum of two distinct cameras being previewed at once. Frames stay in memory and preview counts are temporary. Use **Run analysis** to save an observation for reports and schedules.

The preview uses authenticated short HTTP requests through the existing Next.js/Vercel proxy, without requiring a persistent Vercel connection. The always-on backend performs detection and publishes each frame with its corresponding boxes and geometry; the browser paints them together to avoid overlay drift. Boxes, trails, labels and counting geometry render at the display's resolution and pixel density independently of the camera image's native resolution. They redraw on resize, fullscreen and display-density changes, including while paused.

## What the measurements mean

| Metric | Meaning | Supported sources |
| --- | --- | --- |
| Vehicles/second, vehicles/minute | Unique vehicle tracks crossing the configured line, divided by decoded observation duration | Live video and recent clips |
| Visible mean/peak | Number of detected cars, motorcycles, buses, and trucks in sampled frames | Video and snapshots |
| Image occupancy | Union of vehicle bounding boxes inside the selected image area, divided by that area's size | Video and snapshots |
| Vehicle mix | Crossing counts for video; average visible class counts for snapshots | Video and snapshots |
| A → B / B → A | Crossing directions relative to the oriented counting line; A is the negative cross-product side, B the positive side | Live video and recent clips |

The tracker uses class-aware Hungarian matching with overlap and centroid distance, lost-track expiry, a line deadband, finite-segment intersection, and one count per track. This is a lightweight tracker; occlusions and unstable detections can still affect counts. Recorded HLS and MP4 processing samples roughly eight frames per source second using decoded video time. MJPEG uses elapsed connection time and samples up to eight frames per second.

**A ten-second camera clip yields a ten-second observation**, even when a longer duration was requested. Flow is a sampled rate, not a measured continuous hourly volume. Snapshot cameras cannot establish unique passing-vehicle flow or speed. Occupancy is image-space bounding-box coverage, not calibrated congestion. No physical speed or identity recognition is inferred.

Identical clips successfully analyzed within the last 24 hours are skipped. Unchanged snapshots within an observation are excluded from further samples. Source `Last-Modified` age is shown where available; it is a provider timestamp, not proof of the image's capture time. An analyzed frame is stored per observation, so images can include incidental people or plates without identification.

Each run captures its camera configuration at creation. Changing the line or analysis area does not reinterpret earlier results. Historical detection views use the captured configuration.

## Scheduling and persistence

The service has one dispatcher and two analysis workers. SQLite WAL transactions and a partial unique index prevent concurrent jobs for one camera. The queue, samples, results, saved cameras, configurations, and schedules persist under `data/`; image frames and the cached model are also there. No product records rely on browser storage.

Jobs run once per selected day, using IANA timezone rules. The dispatcher checks every 15 seconds and permits a ten-minute catch-up window. Nonexistent spring DST times are skipped; repeated autumn times run once. A restart marks interrupted jobs failed instead of leaving them stuck. Keep the machine and service running for unattended observations. Multiple Uvicorn workers or multiple service instances sharing one database are unsupported.

Reports group by each camera's local hour. Comparing several timezones does not compare simultaneous UTC observations. Report/export queries include up to the most recent 1,000 observations in the selected period; the report displays a limit notice.

## Deploy to Vercel

Use the [deployment guide](DEPLOYMENT.md). The website uses standard Next.js with Vercel Root Directory `dashboard`. The Python analysis service has an included Render Blueprint and Dockerfile for permanent HTTPS hosting with a persistent disk.

Set Vercel's server-only `ANALYSIS_URL`, `ANALYSIS_KEY`, and `DASHBOARD_PASSWORD`. The API proxy keeps the backend key private. Production sign-in replaces the previous hosting gateway. Backend connection errors explain missing configuration, rejected keys, timeouts, and unreachable services separately.

The prior temporary tunnel expired; it is no longer used. The existing local service, camera records, observations, and schedules remain intact. No cloud resources have been created by this migration.

The local launcher creates ignored `dashboard/.env.local`, starts Next.js, and checks the authenticated backend connection before reporting ready. If a `.next/BUILD_ID` exists it starts the production build; use `scripts/start.ps1 -Development` for live development. After rebuilding, use `scripts/use-built-dashboard.ps1` to restart only the dashboard.

Public media fetches allow only HTTP/HTTPS on ports 80/443, reject non-global DNS addresses and embedded credentials, revalidate redirects, and bound download sizes and durations. HLS playlists rewrite every media/key URL to authenticated, camera-scoped signed resources; every fetch still validates the destination. Video decoders only receive local files, and ffmpeg recording disables network protocols. MJPEG connections renew after 45 seconds in the browser and stop consuming bandwidth in hidden tabs. The production container requires a long service key on all routes except `/health`, initializes its persistent data volume, then drops root privileges. Run one backend instance for the SQLite database and scheduler.

For a local Docker backend, set `FLOWSTATE_API_KEY` in a root `.env` file and run `docker compose up --build -d`. Point the dashboard at that same key and local API origin. See `.env.example` and `dashboard/.env.example`.

## Development and validation

```powershell
.venv\Scripts\python -m pytest -q
cd dashboard
npx tsc --noEmit
npx playwright install chromium
npx playwright test
npm run build
```

Backend tests cover tracking crossings/directions, finite line segments, lost tracks, occupancy unions, input validation, private-source rejection, timezone/DST scheduling, queue concurrency, captured configuration, restart recovery, and clip deduplication. Browser checks cover actual camera analysis, persistent schedule creation/pause/deletion, reports/CSV, mobile layout, and recoverable camera form validation. Browser tests use the running local app and public sources; they create and remove a named validation schedule and retain real camera observations.

Real London MP4 clips and a Finland JPEG were analyzed during validation. A Tower Bridge observation produced a tracked line crossing and a computed flow rate. Detection accuracy has not been benchmarked against manually labeled ground truth. Browser WebMCP tools are feature-detected for camera search and starting analysis; native WebMCP validation was unavailable in the test browser.

## Source references

- [Transport for London open data](https://tfl.gov.uk/info-for/open-data-users/) and [JamCam directory](https://api.tfl.gov.uk/Place/Type/JamCam).
- [Fintraffic road camera API and source attribution](https://www.digitraffic.fi/en/road-traffic/).
- [YOLOX upstream](https://github.com/Megvii-BaseDetection/YOLOX), [official ONNX Runtime example](https://github.com/Megvii-BaseDetection/YOLOX/tree/main/demo/ONNXRuntime), and [Apache 2.0 license](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE).
- [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/). Maps use normal browser tile caching and visible attribution. Switch the tile provider before operating at substantial public scale.

Project structure: `backend/` contains the service, vision, providers, scheduler, and database; `dashboard/` contains the app and hosted proxy; `scripts/` contains launchers; `tests/` contains backend validation. The dashboard dependency lockfile is retained, and `requirements.lock.txt` records the tested Python environment.
