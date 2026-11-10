# Flowstate dashboard

Standard Next.js dashboard for public camera traffic analysis. Deploy this directory to Vercel. See [the deployment guide](../DEPLOYMENT.md) for the persistent Python backend, Vercel settings, and troubleshooting.

For local development, start the whole app with `../scripts/start.ps1` from the project root. It creates ignored `.env.local` settings, starts the analysis service, and verifies the proxy is connected. Use `-Development` for the Next.js development server.

Manual setup: copy `.env.example` to `.env.local`, configure the backend origin/key, then run `npm ci` and `npm run dev`. For a local loopback backend without sign-in, remove `DASHBOARD_PASSWORD` and set `FLOWSTATE_LOCAL=1`; this bypass is rejected on Vercel.

Commands:

- `npm run build`: standard Next.js production build.
- `npm run start`: production server after a build.
- `npm run typecheck`: TypeScript verification.
- `npm run lint`: ESLint.
- `npm test`: browser workflows, configuration guards, and production connection/sign-in tests. Tests expect the local backend and dashboard to be running; production tests also use port 3100.

The app provides camera discovery, saved cameras, real vehicle detections, counting line/area configuration, video and snapshot analysis, persistent schedules, time-of-day reports, and CSV exports. Workspace authentication and the API proxy are server-side.

Dashboard navigation and filters use URL query parameters with Next.js's native History API integration. Browser Back/Forward and reload restore the view without putting product records in browser storage. Historical observation links fetch their run directly, including runs outside the recent list. Sign-in return paths are restricted to this dashboard.

`tests/navigation.spec.ts` uses intercepted API fixtures to check navigation, historical observations, loading/error recovery, chart data, mobile filters, analysis durations, and dialog accessibility without depending on public-camera uptime. Run it alongside `tests/config.spec.ts` for a quick deterministic check. `tests/deployment.spec.ts` verifies saved links through production sign-in.
