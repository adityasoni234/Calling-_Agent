# Platform audit and implementation plan

Verified against the running system, not recalled. Every claim below was
checked with a query or a request; where something is unverified it says so.

**Date:** 2026-10-11 · **Migrations applied:** 0010 · **Backend tests:** 277 passing

---

## 1. What is real today

### Working, verified

| Area | Evidence |
|---|---|
| Auth, JWT + refresh rotation | tested; 18 auth tests |
| Multi-tenancy (org isolation) | tested across leads, calls, agents, API keys |
| **RBAC** — 4 roles, capability table | 12 tests; enforced on 23 endpoints |
| Telephony (Twilio) | live calls placed; adapters for Plivo, Telnyx, mock |
| STT / LLM / TTS pipeline | real conversations; barge-in; ~1.0s first audio |
| Campaigns + dispatch + stale-call reaper | 22 tests |
| Leads, sheets (CSV batches) | 16 tests |
| Credit **ledger** (append-only, balance_after) | 19 tests |
| Usage charging per call (idempotent) | tested: 3 charges → 1 entry |
| Platform admin API + separate admin app | 403/401 enforced; own bundle |
| Learning engine (bandit over phrasings) | 11 tests |
| CRM integration: API keys + signed webhooks | 10 tests; HMAC verified by a live receiver |

### Configured but unverified end-to-end

- **Plivo / Telnyx adapters** — code complete, conformance-tested against the
  shared interface, but no live call has been placed through either. Telnyx key
  returns 401.

### Not configured at all

`RAZORPAY_*`, `STRIPE_*`, `SMTP_*`, `S3_*` — no payment provider, no email, no
object storage. Recordings are provider-hosted URLs.

---

## 2. The highest-risk gap

**Calls cannot be attributed to a person.**

```
calls: organization_id, agent_id, lead_id, campaign_id, direction, provider,
       provider_call_id, from_number, to_number, status, end_reason, error,
       started_at, answered_at, ended_at, duration_seconds, summary,
       extracted_data, recording_url, cost_usd, cost_incomplete, mode,
       operator_number
```

There is **no `user_id`** and **no `source`**. So today the platform cannot answer:

- Which member of the customer's team placed this call?
- Was it manual, API, campaign, scheduled, or inbound?
- Which version of the agent's configuration was live when it ran?

`mode` (`agent` | `human`) is the only origin signal, and it conflates "a human
is on the line" with "a human initiated it". Parts V–VII of the directive rest
on this, so it is Phase 2 and it comes first.

---

## 3. Missing tables (25)

Grouped by what they block.

**Payments (blocks the entire customer purchase flow)**
`credit_packages`, `credit_package_versions`, `orders`, `order_items`,
`payment_transactions`, `payment_webhook_events`, `invoices`,
`idempotency_records`, `refund_requests`, `refund_transactions`, `disputes`

**Credit correctness**
`credit_reservations` — credits are charged *after* a call completes, so an
account with 10 credits can start 20 concurrent calls and go arbitrarily
negative. This is a live money leak, not a future feature.
`credit_lots` — needed for expiry and for partial-refund arithmetic.

**Attribution and investigation**
`agent_versions`, `call_events`, `call_participants`, `usage_records`

**Org structure**
`organization_members` — a user belongs to exactly one organization today, so a
person cannot be in two workspaces and there is no invite flow.

**Other**
`subscription_plans`, `subscriptions`, `subscription_periods`, `pricing_rules`,
`notifications`

Existing equivalents that should be **reused, not duplicated**:
`credit_entries` is the ledger. `organizations.credit_balance` is the account.
`platform_events` is the audit trail. `pricing_rates` holds provider cost.

---

## 4. Known-wrong things found during this audit

1. ~~`Admin` is listed in the **customer** navigation file.~~ **Fixed** —
   removed from `frontend/src/components/nav.ts`.
2. ~~`make relive` rebuilds only the customer app.~~ **Fixed** — it now runs
   `build:all` and verifies the API URL baked into *both* deployed bundles.
3. Telnyx credentials are expired; every tunnel restart logs a 401. **Open.**

### Found later, while building phases 6–7

4. ~~The dev container did not mount `tailwind.config.js`, so it compiled the
   stylesheet against whatever config was baked into the image. Every local
   page had been loading unstyled since the redesign.~~ **Fixed** — the config
   files are mounted in `docker-compose.yml`.
5. ~~Both admin margin figures divided **lifetime** credits consumed by
   **30-day** provider cost, reporting a loss on any account that had been
   quiet lately.~~ **Fixed** — `credits_used_30d` / `consumed_30d` added, with
   a regression test.
6. ~~An account that had never placed a call displayed its spend as
   `-0.00`.~~ **Fixed** — `spend_total()` normalises the sign.
7. **Open, needs your decision.** Order `SV-TJXZHCKC` is still `status=paid`
   with `provider=simulated`, `provider_payment_id=sim_verification_only`.
   It is the end-to-end verification purchase. Its credits were reversed in
   the ledger, so the balance is correct, but the order row still counts as
   ₹1,178.82 of revenue the business never received.

---

## 5. Plan

Phases follow the directive's order. Phases 1–2, 5 and parts of 6 need nothing
external. Phases 3–4 need a payment provider account.

| Phase | Work | Blocked on |
|---|---|---|
| 1 | This audit | — done |
| 2 | **Call attribution**: `user_id`, `source`, `source_detail`, agent version | — |
| 3 | **Credit reservations**: reserve → settle → release | — |
| 4 | Packages + versioned pricing + orders | — |
| 5 | Razorpay: checkout, signed webhooks, idempotent allocation | **your account** |
| 6 | User 360° admin profile + timeline | — done |
| 7 | Customer billing pages + admin package/order UI | — done |
| 8 | Refunds, disputes, reconciliation | **your account** |

Phase 5's code is written and tested; it sits behind `UnconfiguredProvider`
until real keys exist. Phase 7's checkout opens an order, records it, and then
says plainly that online payment is not set up — it never pretends to succeed.

**Deliberate ordering change from the directive:** reservations (phase 3) come
before packages. Packages only matter once payments work; the overspend hole
costs real money on every concurrent call today.

### What cannot be built without you

A payment provider needs **your** merchant account, API keys, and a webhook
registered in **your** dashboard. The integration and its verification logic
will be written and shipped **labelled unconfigured**. Per §20 of the directive,
no simulated purchase will be presented as working.
