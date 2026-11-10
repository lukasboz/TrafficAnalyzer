# Validation record

## Navigation, reports, and accessibility — November 10, 2026

- All **64 backend tests passed**. The initial sandbox run could not access pytest's existing temporary directory; the unrestricted rerun passed.
- **19 frontend checks passed** across configuration, production deployment/sign-in, and the new navigation suite. Coverage includes bookmarks, camera/filter restoration, Back/Forward, historical observations outside the latest 200 runs, clearing stale report data while loading, report failure/retry, fractional hourly averages, measured zeros versus missing observations, invalid URL settings, mobile filter recovery, valid video durations after single-image snapshots, named dialogs, and keyboard focus restoration. Production tests verified that saved report links survive sign-in and external return destinations are rejected.
- All **six existing workflow/catalog browser checks passed**, including a real public Finland snapshot analysis, persistent schedule creation/pause/deletion, CSV export, mobile form validation, all camera-catalog pages, country/network filters, rendered map markers, unlocated cameras, and source-management status. The first live-camera run was blocked by sandbox networking; it passed after restarting the analysis service outside the sandbox.
- The standard Next.js production build, including TypeScript validation, passed. ESLint passed without errors or warnings. Desktop and 390-pixel mobile report screenshots from the production server were inspected; mobile had no horizontal document overflow, and expanded measurement tables use a bounded 320-pixel scroll area. The eight navigation checks also passed again after the final dialog focus change.
- Fixed and exercised the Windows service restart race: stopping the Python child can terminate its launcher before the script stops the parent. Restart and stop now tolerate a process that has already exited while retaining the existing workspace identity checks. Two successive service restarts succeeded.

Dashboard locations use URL parameters and native browser history. New report requests abort obsolete requests and guard against stale results. Chart data is available in native expandable tables; occupancy uses a 0–100% axis, and sample charts connect measured points with straight lines. Product records continue to live in the backend. No cloud deployment was performed during this refinement.

Vercel migration verified locally on October 5, 2026, using Windows, Python 3.12, Node 23.5.0, Chromium, CPU ONNX Runtime, and Next.js 16.3.4. Vercel deployment instructions target its supported Node 24 LTS runtime.

- **36 backend tests passed.** Tracking, finite line crossings, directions, lost tracks, occupancy, scheduling/DST, input validation, public-source restrictions, queue concurrency, restart recovery, saved configuration, duplicate clips, production key/volume safeguards, live session leases, shared workers, preview capacity, synchronized frame metadata, line crossings, replay resets, unchanged-image inference deduplication, and saved-configuration refresh.
- **15 frontend checks passed across the workflow, configuration, deployment, and live-preview suites.** Real public-camera analysis, schedule persistence/pause/deletion, reports/CSV, mobile layout, preserved invalid form input, Vercel configuration guards, production sign-in/sign-out, session persistence, cross-origin rejection, modified signature rejection, missing settings, unreachable service, mismatched backend key, real video detection, frame advancement, hot counting-line updates, preview pause/resume and release, and mobile snapshot previews.
- **Standard Next.js production build passed**, including TypeScript validation. The active local dashboard uses this compiled build.
- **ESLint passed without errors or warnings.**
- **Render Blueprint passed the official Draft 2020-12 JSON schema.** Its paid `1c-2g` plan and persistent disk match the current specification.
- **Docker Compose configuration passed** `docker compose config --quiet`.
- **Live proxy health returned HTTP 200**, reporting model ready, scheduler running, and 1,633 public cameras.
- **Final browser bundles checked:** the local backend key is absent. Environment files, service credentials, camera data, and build output are Git-ignored; the example environment file is included.
- **Sites runtime and hosting manifest removed.** Dashboard commands use standard Next.js, and the old tunnel is stopped.
- **Existing Git history retained** with the repository root moved to TrafficAnalyzer so the frontend and backend can be deployed from the same project.

The four workflow checks use the actual running backend and public sources. Test schedules are removed after verification; real camera observations remain in local history. The snapshot test waits for its specific queued run to complete and inspects that run's frame.

The original vision pipeline was also validated on October 4. A Tower Bridge MP4 observation analyzed 78 frames across 9.32 source seconds, detected an average of 4.15 vehicles, and counted one crossing: 0.1073 vehicles/second (6.44 vehicles/minute). Image-space occupancy was 3.70%. These values demonstrate the measurement pipeline; they are not a ground-truth accuracy benchmark.

The existing saved cameras, observations, and two weekday Tower Bridge schedules remain in the local database. A new remote backend starts with an empty workspace unless data is transferred.

Vercel and Render cloud deployments were not executed in an account. The Docker daemon was unavailable, so container image build/execution remains unverified; its configuration and production safeguards were checked. Native browser WebMCP was unavailable. RTSP ingestion, calibrated physical speed, imagery captured before the service starts, and separate tenant workspaces remain outside this implementation. HLS/MJPEG support was added in the later validation below.

The live-preview tests use real Marylebone Road video and Finland camera imagery. The video preview showed actual vehicle boxes, track IDs, motion trails, and directional line crossings. Its gate change was restored after testing. Live frames/counts remain temporary; no live session writes report observations. Provider clips are explicitly distinguished from stills and replays. Preview session cleanup and saved geometry updates were verified through the authenticated API.

The overlay resolution fix was verified against the production build with both live-preview browser tests passing at 2× display density. Canvas output matches the displayed dimensions and screen pixel density on desktop, mobile, resize and fullscreen. A pixel check confirmed that the counting-line endpoint remains aligned after fullscreen resizing. A paused preview also updated from 2× to 3× density without receiving a new camera frame. The production build and ESLint passed after these changes.

## Global camera directory expansion — October 5, 2026

The local catalog contains 14,094 camera views from 16 directories across 13 countries and territories. All twelve Caltrans districts imported successfully. The catalog includes multiple views at Finland stations and preserves the original station IDs, saved configurations, and observations. These are directory entries; individual cameras may become unavailable, and this catalog is not an exhaustive inventory of public cameras worldwide.

All 49 backend tests passed. New checks cover the actual Hong Kong UTF-16/tab-delimited format, Finland presets, Taiwan snapshots, stable Caltrans IDs, Socrata pagination, idempotent imports, retained data after refresh failure, imports into an existing installation, rotating image URLs, catalog pagination beyond 4,000 entries, unlocated São Paulo cameras, New Zealand availability, and NSW request headers with redirect revalidation.

Six browser checks passed across the workflow and global catalog suites, including a real Finland snapshot analysis, schedule creation/pause/deletion, report CSV, mobile forms, all catalog pages, country/network filters, rendered map markers, unlocated camera monitoring, source attribution, and import timestamps. The Next.js production build, TypeScript, and ESLint passed.

Representative images from all 16 providers were fetched through the authenticated backend and decoded successfully. NSW's public image host requires browser/image request headers; the app still identifies itself as Flowstate. Singapore and Estonia resolve current capture URLs instead of retaining one image indefinitely. São Paulo images load successfully without invented coordinates. These checks verify source integration, not every camera's current uptime or detection accuracy.

## Live video and recent clips — October 5, 2026

The refreshed catalog contains 14,096 entries: 2,309 published HLS stream URLs from Caltrans and Norway, 2,334 continuous MJPEG endpoints from Taiwan, 840 TfL MP4 clip endpoints, and 8,613 still-only cameras. Counts represent published capabilities, rather than a guarantee that each camera is online. The explorer defaults to video feeds; snapshots remain accessible through its feed filter.

All **64 backend tests passed**, including signed HLS resource scope/tamper/expiry, redirect/private-address checks for segments, relative URLs after master redirects, initialization/key URI rewriting, stale/ended playlist rejection, HTTP byte ranges, consuming only new segments, downloading segments before CDN expiry, local-file-only ffmpeg processing, MJPEG parsing/cleanup, stale clip rejection, adapter video retention, and waiting for new clips without replaying finished footage.

Actual Caltrans and Norway HLS segments decoded at 15 fps and 5 fps respectively. Taiwan produced distinct successive JPEG frames from one continuous connection. A three-second Caltrans recording decoded successfully with ffmpeg restricted to local file protocols. A saved 15-second Caltrans live observation analyzed 112 frames, detected an average of 6.78 vehicles and counted 20 crossings. A Taiwan observation sampled 63 live frames over 14.98 seconds with zero detected vehicles. These are integration checks, not accuracy benchmarks.

Browser checks cover HLS playback and a growing stream edge, Go live, mobile MJPEG frames changing continuously, London clip timestamps and completion without automatic replay, video/country/network filters, all catalog pages and map markers, unlocated cameras, source management, actual live HLS vehicle detection, saved geometry updates, pause/resume/session cleanup, sharp overlays on resize/fullscreen/display-density changes, mobile snapshot detection, and the existing analysis/schedule/report/form workflows. A map animation cleanup error found while filtering was fixed. HLS playback promises are handled when navigating away.

The production build and TypeScript validation passed. ESLint passed without errors or warnings. The running local dashboard and backend use the updated code. HLS/MJPEG cameras without capture timestamps are labeled without inventing a capture age; HLS distance from the stream edge does not establish total capture-to-view latency. Encrypted, byte-range and fragmented-MP4 HLS analysis remain unsupported; standard browser playback uses hls.js or native HLS. Cloud streaming deployment and every catalog camera's uptime remain unverified.
