# Cost model

## The rule

**This repo does not ship prices.** Every rate is a database row you enter from a
vendor's live rate card, with the URL and the date you read it. The cost engine
(Phase 9) prices a call by joining usage records to rates; a usage line with no
verified rate makes the call `cost_incomplete` rather than producing a
confident-looking wrong number.

That constraint exists because voice-AI unit economics are decided in the third
decimal place, and a stale hard-coded rate is worse than no rate at all.

## The formula

For one call of duration `D` minutes:

```
cost_call =
      D                    × telephony_rate_per_min(destination, direction)
    + D                    × stt_rate_per_min(model)              # both legs if diarised
    + Σ turns (
          tokens_in_cached   × llm_cached_input_rate_per_1k
        + tokens_in_uncached × llm_input_rate_per_1k
        + tokens_out         × llm_output_rate_per_1k
      )
    + tts_chars_spoken     × tts_rate_per_char        # or per-second, per vendor
    + post_call_tokens     × llm_rates                # summary + extraction
    + D                    × infra_allocation_per_min
```

`infra_allocation_per_min` is derived, not guessed:

```
infra_allocation_per_min = monthly_infra_spend / (concurrent_capacity × utilised_minutes_per_month)
```

## What drives the number (in order)

1. **Telephony minutes.** For a managed CPaaS this is usually the largest single
   line and the one you cannot optimise with better engineering — only with a
   better rate card or a self-hosted SIP trunk. Model it first.
2. **TTS characters.** Directly proportional to how much the agent talks. A prompt
   that makes the agent ask one short question at a time is a *cost* optimisation
   as well as a UX one; premium voices multiply this line several-fold.
3. **STT minutes.** Roughly fixed per call minute. The main lever is
   self-hosting once you have steady concurrency.
4. **LLM tokens.** Usually the *smallest* line on a cheap model — and the one
   people over-optimise. The real risk is quadratic context growth: naive
   re-sending of full history makes turn *n* cost O(n). Rolling summarisation plus
   prompt caching keeps it near-linear.
5. **Infrastructure.** Negligible per call at any real volume; it only dominates
   when you are running a mostly-idle GPU.

## Structural levers, ranked by impact per unit of effort

| Lever | Where |
|---|---|
| Cache the stable system-prompt prefix | Phase 2 prompt builder |
| Shorter agent turns (one question at a time) | Agent config + prompt |
| RAG only when the turn needs facts | Phase 6 retrieval gate |
| Roll up turns older than N into a digest | Phase 4 context manager |
| Hang up promptly on voicemail / no-answer | Phase 3 lifecycle |
| Retry caps and calling windows | Phase 7 campaign engine |
| Cheap TTS voice by default, premium as opt-in tier | Agent voice config |
| Self-host STT/TTS above a measured volume threshold | Adapter swap, no code change |

## Metrics the product must expose

`cost_per_call`, `cost_per_minute`, `cost_per_campaign`, `cost_per_day`,
`cost_per_month`, and the one that actually matters commercially:
**`cost_per_qualified_lead` = campaign spend ÷ leads reaching `QUALIFIED`.**

A campaign with a higher cost per call and a better qualification rate is the
cheaper campaign. The dashboard is built to show that comparison directly.

## Budget enforcement

Configurable at organization and campaign level: a soft threshold that warns, and
a hard cap that pauses dialing. Enforced in the campaign dispatcher before a call
is originated — never after, since an in-flight call cannot be un-billed.

## Filling in the rates

Before production, for each vendor you have actually signed up with:

1. Open the vendor's pricing page, note the rate **for your destination and volume
   tier** (India voice termination and Indian-language ASR are frequently priced
   differently from the US default that gets quoted).
2. Insert a `pricing_rates` row: `provider`, `component`, `unit`, `rate`,
   `currency`, `source_url`, `verified_at`.
3. Re-verify quarterly, and after any contract change.

Then run a real 20-call pilot and compare measured cost per call against the
model. Only the pilot number is real.
