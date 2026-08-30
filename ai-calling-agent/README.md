# AI Calling Agent

A low-cost AI voice agent platform: it places and answers phone calls, holds a
natural conversation in English, Hindi, or Hinglish, answers from your own
business knowledge, and records transcripts, summaries, lead outcomes, and cost.

**Status: all nine phases complete and verified end to end.**

It runs today with **no API keys at all** — every provider defaults to a working
mock, so the full pipeline (origination, live media, barge-in, RAG, campaigns,
summaries, costing) works out of the box. Swap in real providers when you have
their keys: see [`docs/going-live.md`](docs/going-live.md).

## Quick start

```bash
make setup      # writes .env with a generated SECRET_KEY
make up         # builds and starts postgres, redis, backend, frontend
```

To use real providers instead of the mocks, `make configure` prompts for each
API key with hidden input and writes it straight to `.env`.

| | |
|---|---|
| Dashboard | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |

## What it does

- **Agents** — persona, objectives, language (English / Hindi / Hinglish),
  greeting, forbidden rules, qualification questions, objection handling, ending
  and transfer rules, voice, silence timers. Prompts are built from this config
  and are inspectable in the UI.
- **Live calls** — one WebSocket per call carrying 8 kHz mu-law both ways.
  STT → LLM → TTS, streamed at sentence boundaries so the first clause plays
  while the rest generates.
- **Barge-in** — the customer can interrupt at any point, including the greeting.
  Synthesis is cancelled and the carrier's buffer is flushed.
- **Conversation state** — nine states, where a topic change wins over script
  order. Silence prompts, then a polite hang-up.
- **Knowledge base** — PDF/DOCX/TXT/Markdown and FAQs, chunked and embedded into
  pgvector. Retrieved only when a turn needs facts; the agent declines rather
  than inventing when nothing matches.
- **Leads and campaigns** — CSV import, search, calling windows, retry caps, and
  concurrency counted from the database so a restart can never double-dial.
- **After each call** — summary, Pydantic-validated structured extraction, lead
  status and score, follow-up scheduling.
- **Cost** — every unit metered. Nothing is priced without a rate you entered
  with its source; unpriced calls are flagged, never guessed.

Open the dashboard and click **Create your organization** — the first account you
register becomes the owner. To create it from the command line instead:

```bash
make seed email=you@company.com pass='a-real-password' name='Your Name' org='Your Company'
```

Then turn self-registration off by setting `ALLOW_REGISTRATION=false` in `.env`.

`make` on its own lists every target (`logs`, `psql`, `migrate`, `test`, `reset`, …).

## Layout

```
ai-calling-agent/
├── backend/            FastAPI, SQLAlchemy, Alembic
│   └── app/
│       ├── api/        HTTP routes, media WebSocket, telephony webhooks
│       ├── core/       config, security, logging, errors, mu-law codec
│       ├── db/         engine, session, declarative base, column types
│       ├── models/     SQLAlchemy models
│       ├── schemas/    Pydantic request/response models
│       ├── services/   domain logic + telephony/stt/llm/tts/embeddings adapters
│       ├── agents/     conversation manager, state machine, prompt builder
│       └── tasks/      arq worker: campaigns, post-call, ingestion
├── frontend/           React + Vite + TypeScript + Tailwind
├── infrastructure/     Postgres init, nginx config
├── docs/               architecture, provider selection, cost model, phase notes
└── docker-compose.yml
```

## Developing outside Docker

The stack runs fine in Docker, but a host-side loop is faster for the backend:

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Point `DATABASE_URL` at `localhost` instead of `postgres`, then:

```bash
make dev-backend    # uvicorn with reload
make dev-frontend   # vite with HMR
```

## Tests

```bash
make test     # backend suite, SQLite-backed, no Docker required
make lint     # ruff + eslint + tsc
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — system design, the control/media plane split, the latency budget
- [`docs/providers.md`](docs/providers.md) — telephony, STT, LLM, TTS, hosting, and queue selection
- [`docs/cost-model.md`](docs/cost-model.md) — how a call is priced and where the money actually goes
- [`docs/hosting.md`](docs/hosting.md) — **deploying: Firebase Hosting for the dashboard, Render for the API**
- [`docs/going-live.md`](docs/going-live.md) — **the API keys you need, and where to get them**
- [`docs/telephony-decision.md`](docs/telephony-decision.md) — which carrier to invest in, measured not marketed
- [`docs/phase-1.md`](docs/phase-1.md) — foundation: Docker, database, auth, shell
- [`docs/phases-2-9.md`](docs/phases-2-9.md) — agents, telephony, realtime pipeline, barge-in, RAG, campaigns, post-call, cost

## Security notes

- Provider API keys live in `.env` and are read by the backend only. Nothing
  secret is ever exposed to the browser: Vite only inlines `VITE_*` variables,
  and those must stay public values.
- Passwords are bcrypt-hashed. Access tokens are short-lived JWTs; refresh
  tokens are opaque, stored as SHA-256 digests, rotated on use, and revoked
  wholesale when a rotated token is replayed.
- `APP_ENV=production` refuses to boot with a default secret, with `DEBUG=true`,
  or with a wildcard CORS origin.

## Regulatory note

Outbound commercial calling in India is regulated (TRAI/DLT registration,
consent, the DND registry, permitted calling windows). The platform enforces
calling windows and retry caps; obtaining the registrations and consent is the
operator's responsibility before any production dialing.
