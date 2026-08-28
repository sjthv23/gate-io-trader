#!/usr/bin/env bash
set -euo pipefail
cd /workspaces/gate-io-trader

# Load API keys from .env if present (not committed to git)
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Start FastAPI if not already running
if ! pgrep -f "uvicorn web_app:app" >/dev/null 2>&1; then
  nohup python3 -m uvicorn web_app:app --host 0.0.0.0 --port 8765 > /tmp/uvicorn.log 2>&1 &
  sleep 2
fi

# Public mobile URL via Cloudflare quick tunnel (no account required)
if ! pgrep -f "cloudflared tunnel" >/dev/null 2>&1; then
  if [[ ! -x /tmp/cloudflared ]]; then
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
    chmod +x /tmp/cloudflared
  fi
  nohup /tmp/cloudflared tunnel --url http://127.0.0.1:8765 > /tmp/cf.log 2>&1 &
  sleep 8
fi

URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log 2>/dev/null | head -1)
if [[ -n "$URL" ]]; then
  echo "Gate.io dashboard (mobile): $URL"
  echo "$URL" > /tmp/public-url.txt
fi
