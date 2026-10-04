# Flowstate dashboard

The React/Vinext dashboard for the Flowstate traffic observatory. The full application also includes the FastAPI/ONNX Runtime service in the parent workspace. See the root README for setup, measurement definitions, scheduling, validation, and deployment.

Run `npm ci`, then `npm run dev` after starting the analysis service. Configure local `ANALYSIS_URL` and `ANALYSIS_KEY` in ignored `.dev.vars`. The hosted app reads these settings from its server runtime; the key is never sent to the browser.

Build with `npm run build`. Type-check with `npx tsc --noEmit`. Browser checks are in `tests/app.spec.ts` and expect a running app at http://127.0.0.1:3000.

The app supports camera discovery, saved cameras, real vehicle detections, counting line/area configuration, video and snapshot analysis, background schedules, time-of-day reports, and CSV exports.
