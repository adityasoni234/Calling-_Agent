# Architecture

## 1. Shape of the system

A **modular monolith**: one FastAPI process (horizontally scalable), one Postgres,
one Redis. No microservices until a module proves it needs its own scaling curve.

```
                    ┌──────────────────────────┐
                    │  React + Vite dashboard   │
                    │  (static build, nginx)    │
                    └────────────┬─────────────┘
                                 │ HTTPS / JSON  (JWT)
                    ┌────────────▼─────────────┐
                    │      FastAPI (ASGI)      │
                    │  api/v1  ── auth, agents, │
                    │  leads, campaigns, calls, │
                    │  knowledge, analytics     │
                    └──┬────────────┬──────────┘
                       │            │
        ┌──────────────▼──┐   ┌─────▼────────────────────┐
        │ Domain services │   │  Realtime media plane    │
        │ (sync-ish CRUD) │   │  /ws/telephony/{call_id} │
        └──────────┬──────┘   └─────┬────────────────────┘
                   │                │
                   │        ┌───────▼──────────────────┐
                   │        │  Conversation Manager    │
                   │        │  FSM + barge-in + silence│
                   │        └───┬───┬───┬───┬──────────┘
                   │            │   │   │   │
                   │        STT │ LLM│TTS│ RAG
                   │            ▼   ▼   ▼   ▼
                   │        provider adapters (swappable)
                   │
        ┌──────────▼──────────────────────────────────┐
        │  PostgreSQL 16 + pgvector   │   Redis        │
        │  (system of record, RAG)    │  (arq queue,   │
        │                             │  call state,   │
        │                             │  concurrency)  │
        └─────────────────────────────┴────────────────┘
```

## 2. Two planes, one process

The single most important architectural decision: **the control plane and the
media plane share a codebase but never share a request path.**

| | Control plane | Media plane |
|---|---|---|
| Traffic | Dashboard REST calls | Telephony WebSocket audio |
| Latency budget | ~200 ms is fine | every 10 ms is audible |
| Blocking DB work | Normal | Forbidden on the hot path |
| Scaling trigger | Requests/sec | Concurrent calls |

The media plane holds per-call state **in memory** (a `CallSession` object) and
writes to Postgres only at turn boundaries and call end, via fire-and-forget
tasks. Nothing in the audio loop awaits a database round trip.

When concurrency outgrows one box, the media plane is the part that moves to its
own deployment — the module boundary (`app/agents/`, `app/services/*`) is already
drawn so that split is a deployment change, not a rewrite.

## 3. Provider abstraction

Every external voice/telephony vendor sits behind a Protocol in
`app/services/<domain>/base.py`, is registered in a `registry.py`, and is chosen
at runtime by an env var (`TELEPHONY_PROVIDER=plivo`, `STT_PROVIDER=deepgram`, …).

Adapters are built to a **streaming-first** interface, because a request/response
interface cannot be retrofitted into a low-latency one:

- `TelephonyProvider` — `originate()`, `hangup()`, `transfer()`, `answer_response()`,
  `parse_webhook()`, plus a codec descriptor (µ-law 8 kHz for both Plivo and Twilio).
- `STTProvider` — `stream()` -> async iterator of `PartialTranscript | FinalTranscript`,
  with endpointing/VAD events surfaced so the Conversation Manager can barge-in.
- `LLMProvider` — `stream_chat()` -> token iterator; `complete_json()` for
  post-call extraction (Pydantic-validated).
- `TTSProvider` — `stream_synthesize()` -> audio chunk iterator, **cancellable**
  mid-utterance. Non-cancellable TTS is disqualifying for this product.

Cost accounting is part of the interface, not bolted on: every adapter returns a
`UsageRecord` (units, unit type, provider, model) that the cost engine prices.

## 4. Latency budget (target, one conversational turn)

```
customer stops speaking
  ├─ STT endpointing decision        150–300 ms
  ├─ RAG retrieval (only when needed)  0–80 ms
  ├─ LLM time-to-first-token         200–400 ms
  ├─ TTS time-to-first-audio          80–200 ms
  └─ network / jitter buffer          40–100 ms
                                     ─────────────
                            target   500–900 ms to first audio
```

Techniques already assumed by the design: stream LLM tokens into TTS at the first
sentence boundary rather than waiting for the full completion; keep RAG off the
default path; pre-warm provider WebSockets at call setup; co-locate the app with
the telephony PoP.

## 5. Data model spine

```
Organization ─┬─ User
              ├─ Agent ─── KnowledgeBase ─── Document ─── DocumentChunk (vector)
              ├─ Lead ────┐
              ├─ Campaign ┴─ CampaignLead
              └─ Call ─── CallTurn / Transcript / CallUsage (cost lines)
```

Every tenant-owned row carries `organization_id`. Phase 1 ships
`Organization`, `User`, `RefreshToken`; each later phase adds its own tables
through an Alembic revision.

## 6. Phasing

| Phase | Delivers |
|---|---|
| 1 ✅ | Repo, Docker, Postgres+pgvector, JWT auth, base dashboard |
| 2 | Agent CRUD + prompt builder + provider abstraction & registry |
| 3 | Telephony adapter, outbound call lifecycle, webhooks |
| 4 | Realtime STT→LLM→TTS over the media WebSocket |
| 5 | Barge-in, silence timers, conversation FSM |
| 6 | Document ingest, chunking, embeddings, pgvector retrieval |
| 7 | Leads, CSV import, campaigns, controlled concurrency |
| 8 | Post-call summary, structured extraction, lead scoring |
| 9 | Analytics, cost engine, budget limits |
