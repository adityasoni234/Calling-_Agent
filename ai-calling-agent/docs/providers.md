# Provider selection

> **Rule for this repo: no price is hard-coded anywhere in application code.**
> Rates live in a database table (`pricing_rates`, Phase 9) with a `source_url`
> and `verified_at` column. The cost engine refuses to price a usage line whose
> rate has no verified entry — it records the usage and flags the call
> `cost_incomplete` instead of inventing a number. See `docs/cost-model.md`.

Recommendations below are engineering judgements about *architecture fit*
(streaming support, India coverage, cancellability, latency class). The commercial
comparison must be done against live rate cards before you commit.

## Telephony — primary: **Plivo**, secondary: **Twilio**, scale option: **self-hosted SIP**

| | Fit |
|---|---|
| **Plivo** ✅ default | India-registered entity and local DIDs, bidirectional WebSocket audio streaming, straightforward outbound + inbound + transfer, generally positions below Twilio on India voice. |
| **Twilio** | Best documentation and reliability; Media Streams is the reference implementation of the interface we're building to. Keep as the second adapter so the abstraction is proven by two real backends, and as failover. |
| **Exotel / Ozonetel / Knowlarity** | Strong India-native compliance story; evaluate whether their real-time media streaming is bidirectional and low-latency enough — several Indian CPaaS vendors only offer one-way or file-based audio, which cannot support barge-in. |
| **Asterisk / FreeSWITCH + Indian SIP trunk** | The genuine floor on per-minute cost at volume, via `AudioSocket`/`mod_audio_stream`. Costs an ops engineer. Recommended only once you are consistently above roughly a few thousand minutes/day — model it as a fourth adapter, not a rewrite. |

**Compliance is a hard gate in India, not a footnote.** Outbound commercial
calling is governed by TRAI regulations (DLT registration, consent, the
DND/NCPR registry, calling-window restrictions). The platform enforces calling
hours and per-lead retry caps in the campaign engine (Phase 7); the legal
registration is the operator's responsibility and must be in place before the
first production dial.

## STT — primary: **Deepgram**, scale option: **self-hosted faster-whisper**, India option: **Sarvam AI**

- **Deepgram (Nova family)** — true streaming WebSocket, interim results, built-in
  endpointing and VAD events (which is what makes barge-in cheap to implement),
  and among the lowest-priced managed streaming ASR. Default adapter.
- **Self-hosted `faster-whisper` (large-v3-turbo) + Silero VAD** on one shared GPU —
  marginal cost approaches the GPU's hourly rate divided by concurrent streams, so
  it wins decisively at volume. Requires you to build the streaming/endpointing
  layer that Deepgram gives you for free. Ship as an adapter in Phase 4, switch on
  measured volume.
- **Sarvam AI / Reverie** — worth benchmarking specifically for Hindi and
  code-mixed Hinglish, where Indian-language-first vendors often beat generalist
  models on the accent and code-switching that this product lives on.

Benchmark all three on **your own recorded Hinglish calls** before choosing. WER
on English benchmarks does not predict Hinglish performance.

## LLM — primary: **Claude Haiku 4.5**, escalation: **Claude Sonnet 5**

The conversational turn wants the cheapest model that holds a persona, follows a
state machine, and doesn't hallucinate over retrieved context. Haiku 4.5 is the
right default for both latency and cost; keep Sonnet 5 configurable per-agent for
harder scripts. Post-call summarisation and JSON extraction run on the cheap model
too — it's a constrained, schema-validated task.

Adapter also targets OpenAI- and Gemini-compatible endpoints so a self-hosted
`vLLM` deployment (Qwen/Llama class) can be dropped in later behind the same
interface.

Cost control that matters more than model choice:
- keep the system prompt short and **cache it** (prompt caching on a stable prefix
  is the single largest lever — the persona/instructions block is identical on
  every turn of every call for a given agent);
- summarise turns older than N into a rolling digest instead of resending them;
- call RAG only when an intent classifier says the turn needs facts.

## TTS — primary: **Cartesia Sonic** or **Deepgram Aura**, quality tier: **ElevenLabs Flash**, India: **Sarvam**

The selection criteria, in order: (1) **mid-utterance cancellation** — required for
barge-in; (2) time-to-first-audio under ~200 ms; (3) native Hindi/Hinglish voices
that don't mangle code-mixed sentences; (4) price.

- **Cartesia Sonic** / **Deepgram Aura** — lowest-latency streaming class, priced
  well below the premium vendors. Default.
- **ElevenLabs Flash v2.5** — best naturalness, meaningfully more expensive; expose
  as a per-agent quality tier for high-value campaigns.
- **Sarvam TTS** — evaluate for Hindi-dominant scripts.
- **Self-hosted Piper / Kokoro** — near-zero marginal cost, noticeably more robotic;
  reasonable for non-sales flows (reminders, confirmations, OTP-style calls).

## Hosting — one box, close to the telephony PoP

MVP: a single 4–8 vCPU VPS running the Docker Compose stack, plus managed Postgres
once you care about backups. The decisive factor is **region, not price**: put the
app in the same region as the telephony media edge and the Indian customer
(AWS `ap-south-1` Mumbai, or DigitalOcean Bangalore). Saving a few dollars on a
European VPS costs 100–150 ms per turn on every call, which is a worse trade than
it looks.

Egress is small (µ-law 8 kHz ≈ 64 kbit/s per direction), so bandwidth is not the
cost driver — CPU per concurrent call and the provider APIs are.

## Task queue — **Redis + `arq`**

`arq` is asyncio-native, ~one dependency, and shares the app's event-loop idioms;
Celery brings a process model and a config surface this product doesn't need. Used
for campaign dialing, post-call processing, and document ingestion. Redis also
holds the campaign concurrency semaphore and live call state.
