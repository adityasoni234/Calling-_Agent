import { useState } from "react";

import { IntegrationsCard } from "@/components/IntegrationsCard";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";

const BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

interface Snippet {
  id: string;
  label: string;
  blurb: string;
  code: string;
}

const SNIPPETS: Snippet[] = [
  {
    id: "lead",
    label: "Add a lead",
    blurb: "Push a contact from your CRM the moment it is created.",
    code: `curl -X POST ${BASE}/leads \\
  -H "X-API-Key: $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
        "name": "Rahul Dhaka",
        "phone_number": "+919950776773",
        "email": "rahul@example.com"
      }'`,
  },
  {
    id: "call",
    label: "Have an agent call them",
    blurb: "The AI places the call and qualifies them for you.",
    code: `curl -X POST ${BASE}/calls \\
  -H "X-API-Key: $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{ "agent_id": "<agent-uuid>", "lead_id": "<lead-uuid>" }'`,
  },
  {
    id: "bridge",
    label: "Call them yourself",
    blurb: "Rings your own phone first, then connects you to the lead.",
    code: `curl -X POST ${BASE}/calls/bridge \\
  -H "X-API-Key: $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{ "operator_number": "+919812345678", "lead_id": "<lead-uuid>" }'`,
  },
  {
    id: "outcome",
    label: "Read the outcome",
    blurb: "Summary, transcript, score, recording and cost.",
    code: `curl ${BASE}/calls/<call-uuid> -H "X-API-Key: $KEY"`,
  },
  {
    id: "verify",
    label: "Verify a webhook",
    blurb: "Prove a delivery came from us before you trust it.",
    code: `import hashlib, hmac

def verify(secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    # compare_digest, not ==, so timing cannot leak the secret.
    return hmac.compare_digest(expected, signature)`,
  },
];

function Code({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-xl bg-ink-deep px-4 py-3.5 text-xs leading-relaxed text-ink-100">
        <code>{code}</code>
      </pre>
      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          } catch {
            // Clipboard can be blocked; the code is on screen to select.
          }
        }}
        className="absolute right-2.5 top-2.5 rounded-lg bg-white/10 px-2 py-1 text-2xs font-medium text-ink-200 transition-colors hover:bg-white/20"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function ApiPage() {
  const [open, setOpen] = useState<string>(SNIPPETS[0].id);
  const active = SNIPPETS.find((s) => s.id === open) ?? SNIPPETS[0];

  return (
    <div className="space-y-5">
      <PageHeader
        title="API & Integrations"
        description="Plug any CRM into this platform. A key to call in, a signed webhook to be called back on, and the same REST API the dashboard uses in between."
      />

      <Card
        title="Base URL"
        description="Every request goes here. Authenticate with an X-API-Key header — no browser login needed."
      >
        <div className="space-y-3">
          <Code code={`${BASE}`} />
          <Code code={"X-API-Key: cak_xxxxxxxxxxxxxxxxxxxxxxxx"} />
          <p className="text-xs leading-relaxed text-ink-500">
            A key is scoped to your organization and can never see another's
            data. The full schema, including every endpoint and field, is at{" "}
            <code className="rounded bg-ink-100 px-1 py-0.5 text-ink-700">
              {BASE.replace(/\/api\/v1$/, "")}/docs
            </code>
            .
          </p>
        </div>
      </Card>

      <Card
        title="Common calls"
        description="The four requests most integrations need, plus how to verify a webhook."
        flush
      >
        <div className="flex gap-1 overflow-x-auto border-b border-ink-100 px-3 pt-3">
          {SNIPPETS.map((snippet) => (
            <button
              key={snippet.id}
              type="button"
              onClick={() => setOpen(snippet.id)}
              className={`-mb-px shrink-0 whitespace-nowrap rounded-t-xl border-b-2 px-3.5 py-2 text-xs font-medium transition-colors ${
                snippet.id === open
                  ? "border-brand-600 bg-white text-brand-700"
                  : "border-transparent text-ink-500 hover:bg-ink-50 hover:text-ink-800"
              }`}
            >
              {snippet.label}
            </button>
          ))}
        </div>
        <div className="space-y-2.5 px-5 py-4">
          <p className="text-xs text-ink-500">{active.blurb}</p>
          <Code code={active.code} />
        </div>
      </Card>

      <IntegrationsCard />

      <Card
        title="Delivery behaviour"
        description="What to expect from a webhook, so your handler is built for it."
      >
        <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          {[
            [
              "Timing",
              "Queued immediately, sent within ~15 seconds by the worker.",
            ],
            ["Success", "Any 2xx. Anything else is retried, up to 3 attempts."],
            [
              "Dead endpoints",
              "10 consecutive failures disables it. Re-enable above.",
            ],
            [
              "Timeout",
              "10 seconds — reply 2xx fast, then process asynchronously.",
            ],
            [
              "Duplicates",
              "At-least-once. Key off call_id; a retry can repeat one.",
            ],
            [
              "Transport",
              "https only. Payloads carry names and phone numbers.",
            ],
          ].map(([term, detail]) => (
            <div key={term}>
              <dt className="text-xs font-medium text-ink-500">{term}</dt>
              <dd className="mt-0.5 leading-relaxed text-ink-800">{detail}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
