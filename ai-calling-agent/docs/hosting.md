# Hosting

**Frontend on Firebase Hosting, backend on Render (or Railway).**

Firebase Hosting serves static files only. It cannot run FastAPI, hold a
WebSocket, or reach Postgres — so the backend needs a real host. That split is
fine, and it is what the config in this repo assumes.

```
Firebase Hosting            Render
┌──────────────────┐        ┌────────────────────────────┐
│  React dashboard │  HTTPS │  FastAPI  ── Postgres      │
│  (static build)  │───────▶│  arq worker ── Redis       │
└──────────────────┘        └────────────┬───────────────┘
                                         │ wss:// + webhooks
                                         ▼
                                    Twilio / Plivo / Telnyx
```

The carrier talks only to the backend. Firebase never needs to be reachable by
Twilio, and the browser never holds a provider credential.

## 1. Backend first

The frontend needs the backend's URL at build time, so deploy the API first.

**Render** — push to GitHub, then Render → New → Blueprint → pick the repo. It
reads [`infrastructure/render.yaml`](../infrastructure/render.yaml) and creates
the API, the worker, Postgres 16 (which ships with pgvector) and Redis.

Fill in the variables marked `sync: false`:

| Variable | Value |
|---|---|
| `PUBLIC_BASE_URL` | this service's Render URL, e.g. `https://calling-agent-api.onrender.com` |
| `CORS_ORIGINS` | your Firebase origins, comma separated |
| `TWILIO_*`, `DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY` | your provider keys |

`SECRET_KEY` and `TELEPHONY_WEBHOOK_SECRET` are generated for you. Migrations
run from the API container on boot; the worker is set to skip them so the two
cannot race.

**Railway** works the same way with
[`infrastructure/railway.json`](../infrastructure/railway.json) — add Postgres
and Redis plugins, set the same variables, and add a second service with the
start command `arq app.tasks.worker.WorkerSettings`.

> **Do not use a free tier that sleeps.** A sleeping instance cannot answer a
> carrier webhook, so calls fail silently and campaigns stall. Render's starter
> plan stays awake.

## 2. Frontend on Firebase

The project is already wired to **`stockvala-agent`** in
[`.firebaserc`](../frontend/.firebaserc), so there is no `firebase init` step.

```bash
npm install -g firebase-tools
firebase login
```

Point the build at your deployed backend:

```bash
cp .env.production.example .env.production
# edit VITE_API_BASE_URL to https://<your-backend>/api/v1
```

Then:

```bash
npm run deploy
```

That builds and deploys in one step. [`firebase.json`](../frontend/firebase.json)
already sets the SPA rewrite (so deep links like `/calls/abc` work on refresh),
immutable caching for hashed assets, `no-cache` on `index.html`, and the usual
security headers.

**Only `VITE_*` variables reach the browser, and they are baked into the bundle
at build time.** Never put a provider key in one — the backend holds all of
them.

## 3. Point everything at each other

Three URLs have to agree, and every one of them has bitten this project during
development:

1. **`CORS_ORIGINS` on the backend** must list the Firebase origin exactly:
   `https://stockvala-agent.web.app,https://stockvala-agent.firebaseapp.com`
   (plus any custom domain). No trailing slash. Firebase serves the same site
   on both hostnames, so both must be listed. Get this wrong and the dashboard
   loads but every request fails.
2. **`VITE_API_BASE_URL`** must be the backend URL ending in `/api/v1`.
3. **`PUBLIC_BASE_URL`** must be the backend's own public URL. Carriers fetch
   answer documents and open the media WebSocket from it.

Then update the carrier to match:

- **Twilio** → Phone Numbers → your number → Voice URL:
  `https://<backend>/api/v1/webhooks/telephony/twilio/inbound?secret=<TELEPHONY_WEBHOOK_SECRET>`
- **Telnyx** → Call Control Application → webhook URL, same path with `/telnyx/`
- **Plivo** → Application answer URL, same path with `/plivo/`

Outbound calls carry their own per-call callback URLs, so only inbound needs
configuring by hand.

## 4. Verify before trusting it

```bash
curl https://<backend>/api/v1/health
```

Expect `{"status":"ok","database":"ok"}`. Then, in the dashboard's Settings
page, every provider should read **configured** and the mock banner should be
gone. Place one test call to your own phone before pointing a campaign at real
leads.

The one failure that is easy to miss: **WebSocket support**. HTTP can work
perfectly while the media socket is blocked, and the symptom is a call that
connects to silence. Check it explicitly:

```bash
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  https://<backend>/api/v1/media/00000000-0000-0000-0000-000000000000
```

A `101` or a `4404` close means the upgrade works. A `400` or `426` means the
host is not passing WebSockets through.

## 5. Before real traffic

- Set **spend limits** in Settings → they are enforced before a call is placed
- Enter **verified rates** in Settings → Pricing, or every call reports
  `cost incomplete`
- Keep `ALLOW_REGISTRATION=false` — the API is on the public internet
- Use a **strong password**; the login endpoint is reachable by anyone
- Consider rate limiting `/auth/login` at the edge (Render and Cloudflare both
  offer it); Redis is already in the stack if you would rather do it in-app
- **India:** DLT registration, consent records and DND scrubbing are legally
  required before commercial outbound calling, and are separate from anything
  in this repo

## Cost of running it

Roughly, per month, before call charges: a starter web service and worker, a
small Postgres, a small Redis. Firebase Hosting is free at this scale. Check
each provider's current pricing — the numbers move, and this repo deliberately
hard-codes none of them.

Call charges are separate and dominate at volume: see
[`cost-model.md`](cost-model.md).
