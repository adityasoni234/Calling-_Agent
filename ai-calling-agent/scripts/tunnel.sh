#!/usr/bin/env bash
# Start a Cloudflare quick tunnel and point everything at it.
#
# Quick tunnels get a new hostname on every start, which otherwise means
# editing .env and the carrier's webhook by hand each time. This does both,
# then keeps running -- leave the window open for as long as you need calls.
set -euo pipefail

cd "$(dirname "$0")/.."
LOG=$(mktemp)

echo "[tunnel] starting cloudflared..."
cloudflared tunnel --url http://localhost:8000 >"$LOG" 2>&1 &
TUNNEL_PID=$!
trap 'kill $TUNNEL_PID 2>/dev/null || true' EXIT

URL=""
for _ in $(seq 1 40); do
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
    [ -n "$URL" ] && break
    sleep 1
done
if [ -z "$URL" ]; then
    echo "[tunnel] could not determine the tunnel URL" >&2
    cat "$LOG" >&2
    exit 1
fi
echo "[tunnel] $URL"

python3 - "$URL" <<'PY'
import pathlib, sys
url = sys.argv[1]
p = pathlib.Path(".env")
lines = [
    f"PUBLIC_BASE_URL={url}" if line.startswith("PUBLIC_BASE_URL=") else line
    for line in p.read_text().splitlines()
]
p.write_text("\n".join(lines) + "\n")
p.chmod(0o600)
print("[tunnel] .env updated")
PY

# Point every configured carrier's inbound webhook at the new hostname. A quick
# tunnel gets a new name each start, so this has to happen every time or inbound
# calls hit a dead URL.
set +u
# A configured webhook secret must be on every URL we hand a carrier, or the
# carrier's callbacks are rejected and calls strand in `ringing`.
WEBHOOK_SECRET=$(grep '^TELEPHONY_WEBHOOK_SECRET=' .env | cut -d= -f2-)
SECRET_QS=""
[ -n "$WEBHOOK_SECRET" ] && SECRET_QS="?secret=$WEBHOOK_SECRET"

TELNYX_KEY=$(grep '^TELNYX_API_KEY=' .env | cut -d= -f2-)
TELNYX_APP=$(grep '^TELNYX_CONNECTION_ID=' .env | cut -d= -f2-)
if [ -n "$TELNYX_KEY" ] && [ -n "$TELNYX_APP" ]; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' -X PATCH \
        "https://api.telnyx.com/v2/call_control_applications/$TELNYX_APP" \
        -H "Authorization: Bearer $TELNYX_KEY" -H "Content-Type: application/json" \
        -d "{\"webhook_event_url\":\"$URL/api/v1/webhooks/telephony/telnyx/inbound$SECRET_QS\"}")
    echo "[tunnel] telnyx webhook updated (HTTP $code)"
fi

TWILIO_SID=$(grep '^TWILIO_ACCOUNT_SID=' .env | cut -d= -f2-)
TWILIO_TOKEN=$(grep '^TWILIO_AUTH_TOKEN=' .env | cut -d= -f2-)
if [ -n "$TWILIO_SID" ] && [ -n "$TWILIO_TOKEN" ]; then
    for pn in $(curl -sS -u "$TWILIO_SID:$TWILIO_TOKEN" \
        "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_SID/IncomingPhoneNumbers.json" \
        | python3 -c "import sys,json;[print(n['sid']) for n in json.load(sys.stdin).get('incoming_phone_numbers',[])]"); do
        code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
            "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_SID/IncomingPhoneNumbers/$pn.json" \
            -u "$TWILIO_SID:$TWILIO_TOKEN" \
            --data-urlencode "VoiceUrl=$URL/api/v1/webhooks/telephony/twilio/inbound$SECRET_QS" \
            --data-urlencode "VoiceMethod=POST")
        echo "[tunnel] twilio number $pn voice url updated (HTTP $code)"
    done
fi
set -u

docker compose up -d backend worker >/dev/null 2>&1

# The backend takes a few seconds to come back; probing immediately reports a
# spurious 502 from the tunnel.
printf '[tunnel] waiting for the backend'
for _ in $(seq 1 30); do
    if curl -sSf -m 5 http://localhost:8000/api/v1/health >/dev/null 2>&1; then
        echo " ok"
        break
    fi
    printf '.'
    sleep 2
done
echo "[tunnel] public health: $(curl -sS -m 20 "$URL/api/v1/health" || echo unreachable)"
echo "[tunnel] ready. Leave this window open."
wait $TUNNEL_PID
