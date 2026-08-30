# Phases 2–9 — what was built

Phase 1 (repo, Docker, Postgres+pgvector, auth, dashboard shell) is documented in
[`phase-1.md`](phase-1.md). This covers everything after it.

## Phase 2 — agent configuration and provider abstraction

`app/models/agent.py`, `app/agents/prompt.py`, `app/services/*/base.py`, `app/services/registry.py`

An agent is **data, not code**: persona, objectives, language, greeting,
forbidden rules, qualification questions, objection handling, ending and transfer
rules, voice config, silence timers, and a knowledge base. `build_system_prompt()`
assembles it into a byte-stable prefix that can be prompt-cached, with per-turn
context (state, retrieved facts) appended separately — because caching only pays
if the cached half never changes. `GET /agents/{id}/prompt` shows exactly what
the model receives.

Four capabilities sit behind Protocols with a registry selected by env var:
telephony, STT, LLM, TTS (plus embeddings). Every adapter returns `UsageRecord`s —
cost accounting is part of the interface, not bolted on. **Every provider has a
working mock**, so the entire pipeline runs and is tested without a vendor
account.

## Phase 3 — telephony and call lifecycle

`app/services/telephony/{plivo,twilio,mock}.py`, `app/services/call_service.py`, `app/api/v1/endpoints/webhooks.py`

Outbound origination, answer documents (`<Stream bidirectional>` / `<Connect><Stream>`),
lifecycle webhooks mapped to the eight required statuses, hangup, and transfer.
Terminal statuses are final — a late webhook cannot resurrect a finished call.
Two real backends exist specifically so the abstraction is proven by more than one.

## Phase 4 — realtime STT → LLM → TTS

`app/api/v1/endpoints/media.py`, `app/agents/conversation.py`

One WebSocket per call. Audio passes through as 8 kHz mu-law with no transcoding
(the format every provider in the default stack speaks natively). LLM tokens are
flushed to TTS **at sentence boundaries**, so the first clause plays while the
rest is still generating. Synthesis runs on its own queue, decoupled from
generation, so the LLM stream closes as soon as its tokens are done. Audio is
paced to real time — dumping a whole utterance into the carrier's buffer makes
barge-in feel broken. No database round trip happens inside the audio loop.

## Phase 5 — barge-in, silence, conversation state

`app/agents/state.py`, `app/agents/conversation.py`

Transcription is consumed **concurrently with speech from the first millisecond**,
so the customer can interrupt even the greeting. On a speech-start event (or a
multi-word partial, for providers without VAD), synthesis is cancelled and a
`clear` frame flushes what the carrier has already buffered — cancelling locally
alone leaves the agent talking for another second.

The nine-state machine advances on script order but **topic changes win**: a
question moves to `ANSWER_QUESTIONS` when it is asked, not after the pitch. Two
silence timers (prompt, then a polite hang-up) and a hard max-call-duration are
enforced by a watchdog.

## Phase 6 — knowledge base and RAG

`app/services/knowledge/*`

PDF/DOCX/TXT/Markdown extraction, paragraph-aware chunking with overlap,
embedding, and storage in pgvector with an ivfflat cosine index. Retrieval is
**gated**: `_needs_knowledge()` runs only on questions and fact-words, because
retrieving on every turn makes calls slower and more expensive for no benefit.
When nothing clears the similarity threshold, the prompt instructs the agent to
say it will confirm — never to invent. `POST /knowledge/{id}/search` runs the
exact retrieval the agent runs, so you can inspect it before a call.

## Phase 7 — leads, campaigns, controlled concurrency

`app/services/lead_service.py`, `app/services/campaign_service.py`, `app/tasks/worker.py`

Leads with E.164 normalisation, per-organization phone uniqueness, CSV import
that maps real-world column names and reports per-row errors, search and filters.

Campaigns enforce, in order: status, calling window (timezone-aware, wrapping
midnight correctly), organization budget, campaign budget, then **concurrency
counted from the calls table** — not from memory, so a restart or a second worker
can never double-dial. Retries are capped and delayed; `DO_NOT_CALL` leads are
never dialed. An arq cron dispatches every running campaign on a 15-second tick.

## Phase 8 — post-call processing

`app/services/postcall_service.py`

Summary and structured extraction via a forced tool call, **validated with
Pydantic before it touches the database** — a malformed score must not be able to
corrupt lead data. Loose model output is coerced (an unrecognised interest level
falls back to `unknown`); an unparseable response still salvages the summary.
Lead status, interest, score, email and follow-up time are updated, and a
`DO_NOT_CALL` decision is never walked back by a heuristic.

## Phase 9 — analytics and cost

`app/services/cost_service.py`, `app/services/analytics_service.py`

Every metered unit becomes a `call_usage` row. The engine prices what it can from
`pricing_rates` — rows that carry a `source_url` and `verified_at`, entered by
you. **A line with no verified rate is recorded but never guessed**, and the call
is flagged `cost_incomplete`, because a confident wrong number is worse than a
visible gap when margins are decided in the third decimal place. Rates entered
later can be applied retroactively (Settings → Reprice past calls).

Dashboard reports calls, outcomes, funnel, spend by component, campaign
comparison, and the metric that actually decides viability:
**cost per qualified lead**.

## Verification

95 backend tests, plus a full end-to-end run against the live Docker stack that
drives the media WebSocket as a carrier would:

```
register → knowledge base → FAQ ingested → retrieval finds it → agent created
→ prompt built from config → lead created → call originated → 500 audio frames in
→ 127 frames out → 7-turn transcript → both sides captured → call finalised
→ summary generated → structured data extracted → usage metered across
embedding/llm/stt/telephony/tts → unpriced usage flagged not guessed
→ lead re-statused and scored → verified rate recorded with source
→ analytics aggregate → campaign concurrency limit enforced (2 then 0)
→ campaign pause
```

## Known gaps

- Inbound calls: the adapter interface supports them; no inbound route is wired.
- Recording storage: the provider's recording URL is stored, not re-hosted.
- Rate limiting on `/auth/login` — belongs at the edge or in Redis.
- Transfer is a blind transfer; no warm handoff with agent context.
- Tests run on SQLite; migrations are exercised against real Postgres by the
  Docker stack, and CI should also run the suite against Postgres.
