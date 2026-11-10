#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .runtime
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.lock.txt
fi
if [ ! -d dashboard/node_modules/next ]; then
  (cd dashboard && npm ci)
fi
.venv/bin/python -c 'import secrets,pathlib; p=pathlib.Path(".runtime/service.key"); p.write_text(secrets.token_urlsafe(48),encoding="utf-8") if not p.exists() else None'
.venv/bin/python -c 'from pathlib import Path; key=Path(".runtime/service.key").read_text(encoding="utf-8").strip(); Path("dashboard/.env.local").write_text("ANALYSIS_URL=http://127.0.0.1:8000\nANALYSIS_KEY="+key+"\nFLOWSTATE_LOCAL=1\n",encoding="utf-8")'
if ! curl -fsS http://127.0.0.1:8000/health >/dev/null; then
  nohup .venv/bin/python scripts/service.py > .runtime/service.log 2>&1 &
  echo $! > .runtime/service.pid
fi
if ! curl -fsS http://127.0.0.1:3000/api/health >/dev/null; then
  mode=dev
  if [ -f dashboard/.next/BUILD_ID ]; then mode=start; fi
  (cd dashboard && exec node node_modules/next/dist/bin/next "$mode" --hostname 127.0.0.1 --port 3000) > .runtime/dashboard.log 2>&1 &
  echo $! > .runtime/dashboard.pid
fi
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:3000/api/health >/dev/null; then
    echo 'Flowstate is ready at http://localhost:3000. Keep the analysis service running for schedules.'
    exit 0
  fi
  sleep 1
done
echo 'Startup failed. Check .runtime/service.log and .runtime/dashboard.log.' >&2
exit 1
