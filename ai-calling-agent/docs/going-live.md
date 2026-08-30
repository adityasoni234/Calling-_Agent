# Going live: what I need from you

The platform runs **today** with zero credentials — every provider defaults to a
mock, and the whole pipeline (calls, barge-in, RAG, campaigns, summaries,
costing) works end to end. Nothing below is needed to try it.

To place **real phone calls**, four things must become real: telephony, STT,
LLM, TTS. Everything else is optional.

## 1. A public URL (required, free)

Carriers need to reach your webhooks and open the media WebSocket. On a laptop:

```bash
cloudflared tunnel --url http://localhost:8000
```

Copy the `https://…` URL it prints into `PUBLIC_BASE_URL` in `.env`. (`ngrok http 8000` works too.)

## 2. Telephony — pick one

Set these with `make configure`, which prompts for each value with hidden input
and writes straight to `.env` — nothing is echoed, logged, or shared.

**Plivo** (recommended for India) — sign up at console.plivo.com, buy a number,
then Account → Keys:

```
TELEPHONY_PROVIDER=plivo
PLIVO_AUTH_ID=
PLIVO_AUTH_TOKEN=
PLIVO_CALLER_ID=      # the number you bought, E.164, e.g. +9122XXXXXXXX
```

**Telnyx** — portal.telnyx.com. Call Control rather than XML, so the platform
answers and opens the stream by command instead of by answer document. Three
steps in the portal:

1. **Voice → Call Control Applications → Create**. Set the webhook URL to
   `<PUBLIC_BASE_URL>/api/v1/webhooks/telephony/telnyx/status/placeholder` —
   the platform overrides it per call, so the value only has to be valid.
   Copy the application's **Connection ID**.
2. **Phone Numbers → your number → Connection**: assign it to that application.
   (This is what clears the "Required for calls" warning.)
3. **Account → API Keys**: create a key.

```
TELEPHONY_PROVIDER=telnyx
TELNYX_API_KEY=
TELNYX_CONNECTION_ID=
TELNYX_CALLER_ID=      # your number, E.164, e.g. +13195368347
```

**Twilio** (alternative) — console.twilio.com:

```
TELEPHONY_PROVIDER=twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_CALLER_ID=
```

> **India compliance is a hard gate, not paperwork.** Outbound commercial calling
> is governed by TRAI: DLT registration, documented consent, scrubbing against
> the DND/NCPR registry, and permitted calling windows. The platform enforces
> calling windows and retry caps for you; the registrations are yours to obtain
> **before** the first production dial.

## 3. Speech to text

**Deepgram** — console.deepgram.com → API Keys:

```
STT_PROVIDER=deepgram
DEEPGRAM_API_KEY=
STT_MODEL=nova-2
STT_LANGUAGE=multi    # "multi" is what makes Hinglish code-switching work
```

## 4. Language model

**Anthropic** (recommended) — console.anthropic.com → API Keys:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
LLM_MODEL=claude-haiku-4-5
```

Or anything OpenAI-compatible (OpenAI, Groq, Together, self-hosted vLLM):

```
LLM_PROVIDER=openai
OPENAI_API_KEY=
LLM_BASE_URL=          # only for non-OpenAI endpoints
```

## 5. Text to speech — pick one

| Provider | Set | Notes |
|---|---|---|
| Cartesia | `TTS_PROVIDER=cartesia`, `CARTESIA_API_KEY=` | lowest latency, low cost |
| Deepgram Aura | `TTS_PROVIDER=deepgram` (reuses `DEEPGRAM_API_KEY`) | one fewer vendor |
| ElevenLabs | `TTS_PROVIDER=elevenlabs`, `ELEVENLABS_API_KEY=` | best quality, priciest |

Then set the voice per agent in the dashboard (Agents → Edit → Voice ID), or a
default in `TTS_VOICE_ID`.

## 6. Embeddings — only if you use the knowledge base

```
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=
EMBEDDING_MODEL=text-embedding-3-small
```

The mock embedder is deterministic and works, but it is not semantic — retrieval
quality will be poor until this is real.

## 7. Safety rails — set these before your first real campaign

```
DAILY_BUDGET_USD=25            # 0 = no cap; checked before each call is placed
MONTHLY_BUDGET_USD=500
MAX_GLOBAL_CONCURRENT_CALLS=5  # start small
TELEPHONY_WEBHOOK_SECRET=      # any random string; checked on every webhook
```

## 8. Enter your rates

The platform ships **no prices**. Open Settings → Pricing and add a row per
component from the vendor's live rate card, with the URL and the date you read
it. Until a rate exists, calls using that component are flagged
`cost incomplete` rather than priced with a guess. After adding rates, click
**Reprice past calls** to complete earlier ones.

Rates worth entering first, in order of impact: telephony per minute (for
**India**, not the US default), TTS per character, STT per minute, then LLM
per-token in/out.

## Checklist

```
[ ] PUBLIC_BASE_URL points at a public https tunnel or domain
[ ] Telephony provider chosen, keys set, caller ID owned and verified
[ ] DLT / consent / DND compliance in place for Indian outbound
[ ] STT key set, STT_LANGUAGE=multi for Hinglish
[ ] LLM key set
[ ] TTS key set, and a voice ID chosen on each agent
[ ] Embedding key set (only if using the knowledge base)
[ ] Budgets and concurrency caps set
[ ] Verified rates entered in Settings → Pricing
[ ] One supervised test call to your own phone before any campaign
```

Restart after editing `.env`:

```bash
make up
```

Settings in the dashboard will show each provider as **configured** or
**missing**, and the mock banner disappears once all four live-call providers
are real.
