# Phase 1 — foundation

**Delivered:** monorepo, Docker stack, PostgreSQL + pgvector, JWT authentication,
dashboard shell. Verified running end to end.

## 1. Architecture decisions made in this phase

- **Modular monolith.** One FastAPI app, one Postgres, one Redis. Module
  boundaries (`services/telephony`, `services/stt`, …) are drawn now so the
  media plane can be split out later without a rewrite.
- **Two planes, one process.** Dashboard REST traffic and realtime call audio
  never share a request path; see `docs/architecture.md`.
- **pgvector enabled at migration 0001**, not deferred to Phase 6, so the RAG
  migration is a plain `CREATE TABLE`.
- **Roles in the schema from day one** (`owner/admin/operator/viewer`) with a
  `require_role()` dependency already written. RBAC becomes an enforcement
  change, never a migration.
- **No price is hard-coded anywhere.** Rates will live in a `pricing_rates`
  table with `source_url` and `verified_at`.

## 2. Files created

```
backend/app/core/         config.py, security.py, logging.py, errors.py
backend/app/db/           base.py, session.py
backend/app/models/       organization.py, user.py, refresh_token.py
backend/app/schemas/      auth.py, user.py, common.py
backend/app/services/     auth_service.py
backend/app/api/          deps.py, v1/router.py, v1/endpoints/{auth,health}.py
backend/app/main.py
backend/alembic/          env.py, versions/0001_initial_auth.py
backend/tests/            conftest.py, test_auth.py, test_health.py, test_security.py
backend/scripts/          entrypoint.sh, seed.py
frontend/src/lib/         api.ts, queryClient.ts, format.ts
frontend/src/stores/      auth.ts
frontend/src/components/  AppLayout, ProtectedRoute, PhasePlaceholder, ui/*
frontend/src/pages/       LoginPage, RegisterPage, DashboardPage, modules, NotFoundPage
infrastructure/postgres/init/01-extensions.sql
docker-compose.yml, Makefile, .env.example, docs/*
```

## 3. Database

Migration `0001`:

- `CREATE EXTENSION vector` (and `pg_trgm` via the init script, for lead search)
- `organizations` — tenant boundary, carries the timezone campaigns will use
- `users` — scoped by `organization_id`, unique email, bcrypt hash, role enum
- `refresh_tokens` — SHA-256 digest, expiry, revocation, and `replaced_by_id`
  to form the rotation chain

## 4. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | liveness + database reachability |
| POST | `/api/v1/auth/register` | create organization + owner |
| POST | `/api/v1/auth/login` | credentials → token pair |
| POST | `/api/v1/auth/refresh` | rotate refresh token |
| POST | `/api/v1/auth/logout` | revoke one refresh token |
| POST | `/api/v1/auth/logout-all` | revoke every session |
| GET | `/api/v1/auth/me` | current user + organization |
| PATCH | `/api/v1/auth/me` | update profile |
| POST | `/api/v1/auth/change-password` | change password, revoke sessions |

Every error, without exception, is `{"error": {"code", "message", "details?"}}`.

## 5. Frontend

Routes: `/login`, `/register`, `/` (overview), and `/agents`, `/leads`,
`/campaigns`, `/calls`, `/knowledge`, `/settings`. The module routes render an
explicit "ships in Phase N" panel listing that module's scope — the shell states
what does not exist yet rather than showing invented data. Dashboard metric tiles
render `—` with the phase that will populate them.

The API client refreshes a 401 once, single-flight (concurrent 401s share one
refresh call), and clears the session if the refresh fails.

## 6. Environment variables

Required to run Phase 1: `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS`,
`VITE_API_BASE_URL`. Everything else has a working default in `.env.example`.
No provider key is needed. `make setup` generates the secret.

## 7. Verification performed

Backend suite — 28 tests, all passing:

```
make test
```

Covering: registration, duplicate email (409), weak-password rejection (422),
login success/failure, identical error for unknown email and wrong password
(no user-enumeration oracle), missing and forged bearer tokens, `/auth/me`,
profile update, refresh rotation, **rotated-token replay revoking the whole
chain**, logout, password change revoking sessions, bcrypt round-trip, oversized
password rejection, corrupt-hash handling, JWT tamper rejection, and slugging.

Against the live Docker stack:

- All four containers healthy; migration `0001` applied; `vector`, `pg_trgm`
  extensions present; tables `organizations`, `users`, `refresh_tokens` created.
- `GET /api/v1/health` → `{"status":"ok","database":"ok"}`
- Registered a real account over HTTP, called `/auth/me` with the issued token,
  rotated the refresh token, and confirmed replaying the old one returns
  `401 token_reuse_detected`.
- Confirmed the stored password is a `$2b$12$` bcrypt hash, 60 characters.
- CORS preflight from `http://localhost:5173` returns the correct allow-origin.
- Logged in through the dashboard UI, loaded the overview, navigated the module
  routes, and confirmed a deep-link page load keeps the session (hydration
  ordering is correct — no redirect flash to `/login`).

Frontend: `eslint --max-warnings 0` and `tsc --noEmit` both clean; production
build succeeds (≈94 kB gzipped).

## 8. Known gaps, deliberately left for later phases

- No email verification or password-reset flow (needs an email provider).
- No rate limiting on `/auth/login` — belongs at the edge or in Redis; the Redis
  service is already in the stack for it.
- Tests run against SQLite for speed; migration `0001` is exercised against real
  Postgres by the Docker stack, but CI should also run the suite against
  Postgres once the vector-typed models land in Phase 6.
- `require_role()` exists but no endpoint restricts by role yet, because there
  is only one role in use.

## Next: Phase 2 — agent management and provider abstraction

Agent CRUD (persona, objectives, language, greeting, forbidden rules,
qualification questions, objection handling, ending and transfer rules, voice
config), the dynamic prompt builder, and the provider interfaces plus registry
for telephony, STT, LLM, and TTS — with a mock adapter for each, so the pipeline
is testable before any vendor account exists.
