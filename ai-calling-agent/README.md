# AI Calling Agent

A low-cost AI voice agent platform: it places and answers phone calls, holds a
natural conversation in English, Hindi, or Hinglish, answers from your own
business knowledge, and records transcripts, summaries, lead outcomes, and cost.

**Status: Phase 1 complete** — repo, Docker stack, PostgreSQL + pgvector,
JWT authentication, and the dashboard shell. No provider API keys are needed to
run what exists today. See [`docs/architecture.md`](docs/architecture.md) for the
full plan and [`docs/phase-1.md`](docs/phase-1.md) for what this phase delivers.

## Quick start

```bash
make setup     # writes .env with a generated SECRET_KEY
make up        # builds and starts postgres, redis, backend, frontend
```

| | |
|---|---|
| Dashboard | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |

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
│       ├── api/        HTTP routes and dependencies
│       ├── core/       config, security, logging, errors
│       ├── db/         engine, session, declarative base
│       ├── models/     SQLAlchemy models
│       ├── schemas/    Pydantic request/response models
│       ├── services/   business logic; telephony/stt/llm/tts/knowledge adapters
│       ├── agents/     conversation manager and prompt building (Phase 2+)
│       └── tasks/      background workers (Phase 7+)
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
- [`docs/phase-1.md`](docs/phase-1.md) — what Phase 1 built, and how to verify it

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
