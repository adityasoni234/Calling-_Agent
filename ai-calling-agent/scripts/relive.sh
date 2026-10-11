#!/usr/bin/env bash
# Bring the public site back after a tunnel death.
#
# Quick tunnels drop every day or two, and the cloudflared process often stays
# alive while Cloudflare can no longer route to it -- so "is it running?" is not
# the question. This restarts the tunnel and rebuilds the dashboard against the
# new hostname, because the API URL is compiled into the bundle at build time.
set -euo pipefail
cd "$(dirname "$0")/.."

# Docker Desktop is off as often as it is on, and every other step needs it.
if ! docker info >/dev/null 2>&1; then
    echo "[relive] starting Docker Desktop..."
    open -a Docker
    for _ in $(seq 1 60); do
        docker info >/dev/null 2>&1 && break
        sleep 5
    done
    docker info >/dev/null 2>&1 || { echo "[relive] Docker did not start"; exit 1; }
fi

echo "[relive] making sure the stack is up..."
docker compose up -d >/dev/null 2>&1
for _ in $(seq 1 30); do
    curl -sSf -m 5 http://localhost:8000/api/v1/health >/dev/null 2>&1 && break
    sleep 2
done

echo "[relive] restarting the tunnel..."
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2
LOG=$(mktemp)
nohup ./scripts/tunnel.sh >"$LOG" 2>&1 &
for _ in $(seq 1 45); do
    grep -q '^\[tunnel\] ready' "$LOG" && break
    sleep 1
done
grep -E '^\[tunnel\] (https|public health)' "$LOG" || { cat "$LOG"; exit 1; }

URL=$(grep '^PUBLIC_BASE_URL=' .env | cut -d= -f2-)
echo "VITE_API_BASE_URL=$URL/api/v1" > frontend/.env.production

# Both sites, not just the customer one. "firebase deploy --only hosting"
# pushes every target, so building one and deploying both used to ship an
# admin bundle still pointing at a dead tunnel.
echo "[relive] rebuilding and deploying both sites..."
(cd frontend && npm run build:all >/dev/null 2>&1 && npx firebase-tools deploy --only hosting >/dev/null 2>&1)

echo "[relive] verifying..."
code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$URL/api/v1/health")

# Read the API URL back out of each deployed bundle. Checking that the site
# merely loads has never once caught the actual failure, which is a live page
# calling a tunnel that no longer exists.
baked_url() {
    local host=$1 page=$2 prefix=$3 bundle
    bundle=$(curl -s -m 15 -H 'Cache-Control: no-cache' "https://$host/$page?cb=$RANDOM" \
             | grep -o "$prefix-[A-Za-z0-9_-]*\.js" | head -1)
    [ -n "$bundle" ] || return 1
    curl -s -m 25 "https://$host/assets/$bundle" \
        | grep -o 'https://[a-z-]*\.trycloudflare\.com' | head -1
}

app_baked=$(baked_url stockvala-agent.web.app "" index || true)
admin_baked=$(baked_url stockvala-admin.web.app admin.html admin || true)

echo
echo "  tunnel        : $URL (HTTP $code)"
echo "  app points at : ${app_baked:-unknown}"
echo "  admin points  : ${admin_baked:-unknown}"
if [ "$app_baked" = "$URL" ] && [ "$admin_baked" = "$URL" ] && [ "$code" = "200" ]; then
    echo "  status        : OK -- hard-refresh both sites (Cmd+Shift+R)"
else
    echo "  status        : MISMATCH -- the deploy may still be propagating; re-run in a minute"
    exit 1
fi
