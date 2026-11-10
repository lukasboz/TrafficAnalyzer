# Deploy Flowstate to Vercel

The dashboard is a standard Next.js app. Deploy `dashboard/` to Vercel and deploy the Python vision service to an always-on host. The included Render Blueprint provisions the latter with persistent storage. Both deployments use this repository.

The old temporary tunnel expired. No tunnel, Sites runtime, or Cloudflare Worker is used by this version.

## 1. Deploy the analysis service

Push the **whole TrafficAnalyzer project**, including `backend/`, `dashboard/`, `Dockerfile`, `requirements.lock.txt`, and `render.yaml`, to your GitHub repository. The Git repository root is now TrafficAnalyzer; existing history is retained. Add or update your Git remote to your GitHub repository before pushing.

In Render, create a **Blueprint** from that repository using the root `render.yaml`. Review the configured **paid 1 CPU / 2 GB service (`1c-2g`) and 5 GB disk** before creating it. This configuration provides room for CPU inference and two analysis workers; it is not a free hosting configuration.

The Blueprint sets:

- Dockerfile: `./Dockerfile`; build context: repository root.
- One always-on service with a disk mounted at `/data`.
- A generated secret `FLOWSTATE_API_KEY`.
- Public health check: `/health`.
- Production authentication enforcement.

The entrypoint initializes the mounted directory, drops root privileges, listens on Render's `PORT`, and runs one Uvicorn process. Keep one instance: the scheduler and SQLite database are designed for a single service instance.

Wait for Render to report healthy. Open `https://YOUR-SERVICE.onrender.com/health`: it should return `{"status":"ok"}`. The model and camera directories load asynchronously on first startup. A healthy process can still show the model as loading in the dashboard.

Copy the generated `FLOWSTATE_API_KEY` from Render's Environment page. Keep it private.

You can use another Docker host with HTTPS and a persistent `/data` volume instead. A sleeping service will miss scheduled observations outside the ten-minute catch-up window.

## 2. Deploy the dashboard to Vercel

Import the same Git repository into Vercel with these settings:

| Setting | Value |
| --- | --- |
| Framework | Next.js |
| Root Directory | `dashboard` |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Output Directory | Default |
| Node.js | 24 LTS |

Set these **server-side environment variables** for Production:

| Variable | Value |
| --- | --- |
| `ANALYSIS_URL` | Your permanent backend HTTPS origin, e.g. `https://YOUR-SERVICE.onrender.com` |
| `ANALYSIS_KEY` | Exactly the backend's `FLOWSTATE_API_KEY`, at least 32 characters |
| `DASHBOARD_PASSWORD` | A long private workspace password, at least 12 characters |

Do not add `/api` to `ANALYSIS_URL`. Do not use `localhost`, a temporary tunnel, or `NEXT_PUBLIC_` prefixes. The backend key stays in Vercel's server-side proxy and is never included in browser JavaScript.

Set the same variables for Preview deployments if you want them to work. Preview deployments share production data when they use the same backend. Use a separate backend for isolated previews.

Deploy. Sign in with `DASHBOARD_PASSWORD`. The session lasts seven days; signing out clears the browser session. Changing the password or service key invalidates existing session signatures. This is one shared workspace, rather than separate accounts per visitor.

The build succeeds without deployed credentials. Missing credentials fail closed at runtime with a configuration page and specific API errors. Environment changes require a redeployment.

## 3. Verify the deployment

1. The Vercel app opens its sign-in page. A wrong password is rejected.
2. After signing in, the top bar says **Analysis service online** and the public cameras load.
3. Pick a camera, open Live detection, and check that frames advance with boxes and the counting line. Pause/resume the feed, then run a saved analysis and open Detection view.
4. Create a schedule, reload, and verify it persists.
5. Open Traffic reports and download a CSV.
6. Close the browser: the backend scheduler continues running.

Camera media and API responses stream through the authenticated Next.js proxy. This avoids buffering large MP4 clips as a Vercel function response. Saved analysis is queued quickly; inference runs on the backend. Live detection uses leased backend preview workers and short authenticated frame requests through Vercel. It needs no WebSocket or long-lived Vercel function. Preview sessions expire after 15 seconds without a viewer; at most two distinct cameras are processed concurrently.

Live HLS playback requests playlists and segments separately through signed, camera-scoped proxy URLs. MJPEG playback uses bounded multipart responses: the backend ends each connection after 50 seconds and the browser renews every 45 seconds. The route's maximum duration is 120 seconds. The Docker backend installs ffmpeg for recording HLS analysis windows; non-Docker installations need ffmpeg on PATH. Cloud streaming behavior has not been exercised in a deployed account.

## Connection troubleshooting

| Error | Fix |
| --- | --- |
| `BACKEND_NOT_CONFIGURED` | Set a valid `ANALYSIS_URL` HTTPS origin in Vercel and redeploy |
| `BACKEND_KEY_NOT_CONFIGURED` | Set `ANALYSIS_KEY` to the long generated backend secret |
| `BACKEND_NOT_PUBLIC` | Replace localhost, HTTP, or a temporary tunnel with permanent HTTPS hosting |
| `WORKSPACE_NOT_CONFIGURED` | Set `DASHBOARD_PASSWORD` to at least 12 characters |
| `BACKEND_KEY_REJECTED` | Match Vercel's `ANALYSIS_KEY` with Render's `FLOWSTATE_API_KEY` |
| `BACKEND_UNREACHABLE` | Check the backend is running and its public `/health` responds; verify the hostname |
| `BACKEND_TIMEOUT` | Inspect the backend logs and resource usage; retry the request |
| `BACKEND_REDIRECTED` | Point directly at the backend HTTPS origin without a redirecting login gateway |
| `SIGN_IN_REQUIRED` | Sign in again; the session may have expired |

A camera image can fail while the analysis service is healthy. Check the provider's camera URL and source availability in that case.

## Preserve existing local observations

Local history remains in `data/`. New remote deployments start with an empty database.

To transfer history, stop the local analysis service and the remote service, then copy `data/flowstate.sqlite3` and `data/frames/` to the remote persistent `/data` volume. Copy the database's WAL/SHM files too if they still exist after shutdown. Use the container's UID/GID 10001 for transferred files and directories. Restart the remote service and verify schedules, saved cameras, and history. The model can download again automatically. Back up the persistent data directory regularly.

## Why the backend has its own host

This implementation runs a continuous scheduler, CPU inference workers, and a local SQLite database. Vercel Functions run on demand with bounded execution and ephemeral storage. Keeping this backend on an always-on host preserves those behaviors without changing the measurement pipeline.

References: [Vercel Next.js deployment](https://vercel.com/docs/frameworks/full-stack/nextjs), [Vercel Function limits](https://vercel.com/docs/functions/limitations), [Vercel response streaming](https://vercel.com/kb/guide/how-to-bypass-vercel-body-size-limit-serverless-functions), [Render Blueprint specification](https://render.com/docs/blueprint-spec), and [Render persistent disks](https://render.com/docs/disks).

Deployment files are provided and local production execution is verified. This change does not create cloud resources or deploy into a Vercel/Render account.
