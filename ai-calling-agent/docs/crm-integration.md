# Plugging a CRM into the calling agent

Nothing here is specific to one CRM. Two pieces: an **API key** so your system
can call in, and a **webhook** so it gets told what happened without polling.

## 1. Get an API key

Dashboard → **Settings → Integrations → Create key**. The key is shown once, on
creation, and is never recoverable — only its hash is stored, for the same
reason passwords are hashed. Copy it then.

Send it on every request:

```
X-API-Key: cak_xxxxxxxxxxxxxxxxxxxxxxxx
```

It reaches the same REST API the dashboard uses, scoped to your organization
only. A key from one organization can never see another's data.

Revoke from the same screen. Revocation takes effect on the next request.

## 2. The calls you will actually make

```bash
# Add a lead your CRM just created
curl -X POST https://your-host/api/v1/leads \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"name":"Rahul Dhaka","phone_number":"+919950776773","email":"r@example.com"}'

# Have an agent call them now
curl -X POST https://your-host/api/v1/calls \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"agent_id":"<agent-uuid>","lead_id":"<lead-uuid>"}'

# Or bridge one of your own people to the lead
curl -X POST https://your-host/api/v1/calls/bridge \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"operator_number":"+919812345678","lead_id":"<lead-uuid>"}'

# Read the outcome
curl https://your-host/api/v1/calls/<call-uuid> -H "X-API-Key: $KEY"
```

Full schema at `/docs` on your deployment.

## 3. Receive events

Dashboard → **Settings → Integrations → Add webhook**, or:

```bash
curl -X POST https://your-host/api/v1/integrations/webhooks \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://your-crm/hooks/calling-agent","events":["call.completed","lead.qualified"]}'
```

The response carries a **signing secret**, shown once. Store it.

`https` is required. Payloads carry lead names, phone numbers and call
summaries, and those should not travel in clear text. `http://localhost` is
allowed so you can develop against a local receiver.

### Events

| Event | When |
|---|---|
| `call.completed` | A call ended and post-call processing finished |
| `lead.qualified` | That call left the lead `qualified` or `converted` |
| `lead.status_changed` | A lead's status changed |
| `call.started` | A call was placed |

### Payload

```json
{
  "event": "call.completed",
  "sent_at": "2026-09-25T09:00:00+00:00",
  "data": {
    "call_id": "…",
    "status": "completed",
    "duration_seconds": 84,
    "cost_usd": 0.071,
    "recording_url": "https://…",
    "summary": "Trades forex on MetaTrader 5, wants a callback.",
    "outcome": "interested",
    "interest_level": "medium",
    "lead_score": 65,
    "followup_opt_in": true,
    "lead": {
      "id": "…", "name": "Rahul Dhaka", "phone_number": "+919950776773",
      "email": "r@example.com", "status": "interested"
    }
  }
}
```

### Verifying a delivery

Every request carries:

```
X-Calling-Agent-Event:     call.completed
X-Calling-Agent-Timestamp: 1758790000
X-Calling-Agent-Signature: <hex hmac-sha256>
```

Recompute and compare:

```python
import hashlib, hmac

def verify(secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

Sign over the **raw body**, not a re-serialised copy — re-encoding changes
whitespace and key order and the signature will not match. Use
`compare_digest`, not `==`, so a timing difference cannot leak the secret.

The timestamp is inside the signed content so a captured delivery cannot be
replayed later. Reject anything more than a few minutes old.

### Delivery behaviour

- Queued first, sent by the worker within ~15 seconds. An event survives a
  crash between "it happened" and "we told you".
- Any 2xx is success. Anything else is retried, up to **3 attempts**.
- **10 consecutive failures disables the endpoint** rather than retrying
  forever against a URL nobody is listening on. Re-enable from Settings; the
  failure count resets.
- `GET /integrations/webhooks/{id}/deliveries` shows the last 50 attempts with
  response codes and errors — the first thing to check when one "did not
  arrive".
- **Send a test event** from Settings before a real call depends on it.

## 4. Two things worth doing on your side

Respond **2xx immediately** and process asynchronously. We time out at 10
seconds, and a slow handler turns into a retry storm.

**Treat deliveries as at-least-once.** A retry after a timeout you actually
processed means the same `call_id` can arrive twice. Key off it.
