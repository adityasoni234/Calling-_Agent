# Which telephony platform to invest in

**Use case:** an AI calling agent dialling leads worldwide, on a conversation
engine you own.

Everything below was measured against the live APIs on 30 Aug 2026, not taken
from marketing pages. Prices are indicative and must be re-verified against each
vendor's rate card before you commit — see `cost-model.md`.

## The four, measured

### Twilio — widest coverage, highest price

Verified working: credentials, geo permissions (India enabled at signup), TwiML
`<Connect><Stream>`, inbound via Voice URL, full webhook lifecycle.

- **Coverage:** the widest of any provider. One integration reaches nearly every
  country, and DIDs are purchasable in most of them.
- **Docs and support:** the best in the industry. You *will* hit strange edge
  cases at 2am; this is when it matters.
- **Cost:** the most expensive per minute of the three real carriers.
- **Friction found:** trial cannot call unverified numbers, cannot place
  verification calls, and never billed six India attempts (`price: null`) —
  all resolved by upgrading.

### Telnyx — owns its network, best cost/quality balance

Verified working: Call Control origination, `streaming_start` with
`stream_bidirectional_mode: rtp` PCMU, webhook lifecycle, number assignment.

- **Owns its own network** rather than reselling. That means better margins,
  more control over routing quality, and typically lower prices than Twilio.
- **Coverage:** good, though narrower than Twilio.
- **Friction found:** pretrial refuses India entirely (`"You must upgrade your
  account in order to use the following countries: IN"`). Outbound Voice Profile
  whitelists countries explicitly — a safety feature once you understand it.

### Plivo — strongest for India, competitive globally

Verified working: adapter at full parity (`<Stream bidirectional="true">`,
inbound, ring timeout). Account holds ₹1,000 in trial credits.

- **India-native.** Calls into India are domestic traffic, not filtered foreign
  routes. Competitive rates in Asia generally.
- **Friction found:** Indian DIDs require business KYC — but Plivo actually
  *offers* the path ("approved in less than 5 minutes") where Twilio and Telnyx
  simply refuse.

### OmniDimension — not a telephony platform

A hosted voice-agent product that happens to sell numbers.

- **Sells Indian numbers instantly** ($5.06/month), no KYC wait. Genuinely
  solves the India cold-start problem.
- **But it replaces the conversation engine.** No media socket: their agent runs
  STT, LLM, TTS and the audio loop. Prompts, barge-in and the state machine move
  to their UI.
- **US numbers were not available** to our account — for a worldwide operation
  that alone is disqualifying.
- **Bundled per-minute pricing**, so no component-level cost visibility, which
  was priority #1 in the brief.
- Concurrency was capped at 1 on the current plan.

## Recommendation

**Start on Twilio. Migrate to Telnyx at volume. Keep Plivo for India.**

That sequencing is deliberate:

1. **Twilio first**, because at low volume the per-minute difference is a few
   dollars a month, while coverage and support are worth far more. You are
   dialling leads *worldwide* — Twilio is the one provider where "does it work
   in country X" is reliably yes. Optimise for learning speed now; cost later.

2. **Telnyx at volume**, once you are calling enough minutes that the per-minute
   delta exceeds the cost of your attention. Owning their network shows up as
   both lower price and better routing control. The adapter is already written
   and tested, so this is an `.env` change.

3. **Plivo for India**, if India becomes a major market. Indian recipients
   answer `+91` numbers and ignore foreign ones — a local DID is not a nicety,
   it decides your pickup rate. Complete the KYC.

**Do not build the business on OmniDimension.** It is the right tool for one
job: proving a call works in India today while your own DID paperwork clears.
Using it long-term means renting the part of the product you built.

## The point of the abstraction

Every provider above sits behind the same `TelephonyProvider` interface, and all
four are implemented and tested. Switching is one environment variable — no code
change, no migration.

That means this decision is **reversible**, and you should not agonise over it.
Pick Twilio, start calling, and let measured cost per qualified lead tell you
when to move.

## What actually decides answer rates

Worth stating plainly, because it outweighs the choice of vendor:

- **Local caller ID per market.** A foreign number gets ignored almost
  everywhere, not just India. Budget for DIDs in each major market.
- **Regulatory compliance per country.** India needs DLT registration, consent
  and DND scrubbing. The US has DNC lists and state-level rules. The EU has
  ePrivacy and GDPR. This is an operational burden, not a technical one, and it
  is the real cost of "leads all over the world".
- **Calling windows in the lead's timezone.** Already enforced by the campaign
  engine — configure it per market rather than per account.
