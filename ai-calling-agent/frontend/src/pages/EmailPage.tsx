import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { TextArea } from "@/components/ui/Inputs";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState, Pager, Table } from "@/components/ui/Table";
import {
  useControlEmailCampaign,
  useCreateEmailCampaign,
  useEmailCampaigns,
  useEmailMessages,
  useEmailReadiness,
  useEmailSuppressions,
  useRemoveEmailSuppression,
  useSendEmail,
  useValidateAddresses,
  useValidateEmailCampaign,
} from "@/hooks/api";
import { formatDateTime, formatUsd } from "@/lib/format";

/**
 * Bulk email.
 *
 * The validation tab exists because email fails differently from phone: an
 * address can be perfectly formed, have working MX, and still end a sending
 * reputation. Nothing here claims an address is deliverable — every verdict
 * shows the method that produced it and a confidence that never reaches 100.
 */

const TABS = [
  { key: "validate", label: "Check a list" },
  { key: "send", label: "Send one" },
  { key: "campaigns", label: "Campaigns" },
  { key: "history", label: "Delivery reports" },
  { key: "blocked", label: "Blocked" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** What each verdict means in words someone can act on. */
const VERDICT_HELP: Record<string, string> = {
  valid: "Every check passed. Not a promise it is deliverable.",
  risky: "A known risk — role account, disposable or free provider.",
  invalid: "Syntax or domain failed. Never sent.",
  suppressed: "Bounced, complained or unsubscribed. Never sent.",
  unknown: "Checks could not finish. Worth retrying.",
};

export function EmailPage() {
  const [tab, setTab] = useState<TabKey>("validate");
  const readiness = useEmailReadiness();
  const blockers = readiness.data?.blockers ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Email"
        description="Addresses are checked before anything is sent, and a bounce blocks that address for good."
      />

      {blockers.length > 0 && (
        <Alert tone="warning">
          <strong className="font-medium">Email is not ready to send.</strong>
          <ul className="mt-1.5 space-y-1">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </Alert>
      )}

      <div className="flex flex-wrap gap-1.5 border-b border-ink-200/60 pb-px">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              tab === item.key
                ? "border-brand-700 text-ink-900"
                : "border-transparent text-ink-500 hover:text-ink-800"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "validate" && <Validate />}
      {tab === "send" && <SendOne />}
      {tab === "campaigns" && <Campaigns />}
      {tab === "history" && <History />}
      {tab === "blocked" && <Blocked />}
    </div>
  );
}

// --- validation -------------------------------------------------------

function Validate() {
  const [raw, setRaw] = useState("");
  const [checkDns, setCheckDns] = useState(true);
  const validate = useValidateAddresses();
  const result = validate.data;

  const addresses = raw
    .split(/[\s,;]+/)
    .map((a) => a.trim())
    .filter(Boolean);

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[1fr_22rem]">
      <Card
        title="Results"
        description="Each verdict names the check that produced it, so you can judge how much it is worth."
        flush
      >
        <div className="px-5">
          {!result ? (
            <EmptyState
              title="Nothing checked yet"
              hint="Paste addresses on the right to see what you actually have."
            />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-ink-200/60 py-4 sm:grid-cols-5">
                {(
                  [
                    ["valid", result.valid],
                    ["risky", result.risky],
                    ["invalid", result.invalid],
                    ["suppressed", result.suppressed],
                    ["unknown", result.unknown],
                  ] as const
                ).map(([key, value]) => (
                  <div key={key}>
                    <p className="font-display text-xl tabular-nums text-ink-900">
                      {value}
                    </p>
                    <p className="mt-0.5 text-2xs capitalize text-ink-500">
                      {key}
                    </p>
                  </div>
                ))}
              </div>
              {result.duplicates_removed > 0 && (
                <p className="py-3 text-xs text-ink-500">
                  {result.duplicates_removed} duplicate
                  {result.duplicates_removed === 1 ? "" : "s"} removed before
                  checking.
                </p>
              )}
              <Table
                headers={[
                  "Address",
                  "Verdict",
                  "Checked by",
                  "Confidence",
                  "Why",
                ]}
              >
                {result.results.map((row) => (
                  <tr key={row.address}>
                    <td className="font-mono text-2xs">{row.address}</td>
                    <td>
                      <Badge value={row.verdict} />
                    </td>
                    <td className="text-xs text-ink-500">
                      {row.method.replace(/_/g, " ")}
                    </td>
                    <td className="tabular-nums text-ink-500">
                      {row.confidence}%
                    </td>
                    <td className="max-w-xs text-xs leading-relaxed text-ink-500">
                      {row.reason ?? VERDICT_HELP[row.verdict]}
                    </td>
                  </tr>
                ))}
              </Table>
              {result.truncated && (
                <p className="py-3 text-xs text-ink-400">
                  Showing the first 500. Every address was checked and cached.
                </p>
              )}
            </>
          )}
        </div>
      </Card>

      <Card
        title="Check addresses"
        description="One per line, or comma separated."
      >
        <div className="space-y-4">
          <TextArea
            label="Addresses"
            rows={10}
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={"someone@example.com\nanother@example.com"}
            hint={`${addresses.length} address${addresses.length === 1 ? "" : "es"}`}
          />
          <label className="flex items-start gap-2.5 text-xs leading-relaxed text-ink-600">
            <input
              type="checkbox"
              checked={checkDns}
              onChange={(e) => setCheckDns(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Check that each domain can receive mail. Slower, and the only way
              to tell a real domain from a typo.
            </span>
          </label>
          <Button
            className="w-full"
            disabled={!addresses.length || validate.isPending}
            onClick={() => validate.mutate({ addresses, check_dns: checkDns })}
          >
            {validate.isPending ? "Checking…" : "Check"}
          </Button>
          <p className="rounded-xl bg-ink-50 px-3.5 py-3 text-2xs leading-relaxed text-ink-600">
            A passing check means the domain accepts mail. It is not a promise
            the mailbox exists — nothing short of a delivery proves that, which
            is why no verdict is ever shown at 100%.
          </p>
        </div>
      </Card>
    </div>
  );
}

// --- single send ------------------------------------------------------

function SendOne() {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [from, setFrom] = useState("");
  const [allowRisky, setAllowRisky] = useState(false);
  const send = useSendEmail();
  const sent = send.data;

  return (
    <div className="grid items-start gap-5 xl:grid-cols-2">
      <Card
        title="Compose"
        description="Checked against your blocked list before it goes."
      >
        <div className="space-y-4">
          <Field
            label="To"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          <Field
            label="From"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder="hello@yourdomain.com"
            hint="Must be a domain you have verified with your email provider."
          />
          <Field
            label="Subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
          <TextArea
            label="Message"
            rows={8}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          {/* An address can be flagged for a reason the sender disagrees
              with -- a shared sales@ inbox they genuinely want to reach. The
              block stays the default; this makes overriding it a decision
              rather than a dead end. */}
          <label className="flex items-start gap-2.5 text-xs leading-relaxed text-ink-600">
            <input
              type="checkbox"
              checked={allowRisky}
              onChange={(e) => setAllowRisky(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Send even if the address is flagged risky — a shared inbox like
              sales@ or info@, or a disposable address. Addresses that bounced
              or unsubscribed are never sent either way.
            </span>
          </label>
          <Button
            disabled={!to || !subject || !body || send.isPending}
            onClick={() =>
              send.mutate({
                to_address: to,
                subject,
                text_body: body,
                from_address: from || undefined,
                allow_risky: allowRisky,
              })
            }
          >
            {send.isPending ? "Sending…" : "Send"}
          </Button>
          {send.isError && (
            <Alert tone="error">
              {(send.error as Error)?.message ?? "Could not send."}
            </Alert>
          )}
        </div>
      </Card>

      <Card title="Result" description="What happened, and why.">
        {!sent ? (
          <EmptyState title="Nothing sent yet" />
        ) : (
          <dl className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-ink-500">Status</dt>
              <dd>
                <Badge value={sent.status} />
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-ink-500">Validation verdict</dt>
              <dd className="text-ink-900">{sent.verdict_at_send ?? "—"}</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-ink-500">Charge</dt>
              <dd className="tabular-nums text-ink-900">
                {formatUsd(sent.customer_charge_usd)}
              </dd>
            </div>
            {sent.error_message && (
              <Alert tone="warning">
                {sent.error_message}
                {sent.verdict_at_send === "risky" && (
                  <span className="mt-1.5 block">
                    Tick &ldquo;send even if flagged risky&rdquo; to send it
                    anyway.
                  </span>
                )}
              </Alert>
            )}
          </dl>
        )}
      </Card>
    </div>
  );
}

// --- campaigns --------------------------------------------------------

function Campaigns() {
  const campaigns = useEmailCampaigns();
  const create = useCreateEmailCampaign();
  const validate = useValidateEmailCampaign();
  const control = useControlEmailCampaign();
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [from, setFrom] = useState("");
  const [error, setError] = useState<string | null>(null);

  const act = async (id: string, action: string) => {
    setError(null);
    try {
      await control.mutateAsync({ id, action });
    } catch (err) {
      setError((err as Error)?.message ?? "That did not work");
    }
  };

  const rows = campaigns.data ?? [];

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[1fr_21rem]">
      <Card
        title="Campaigns"
        description="Validate, confirm you have consent, then send. In that order."
        flush
      >
        {error && (
          <div className="px-5 pt-4">
            <Alert tone="error">{error}</Alert>
          </div>
        )}
        {!rows.length ? (
          <EmptyState
            title="No campaigns yet"
            hint="Create one on the right. Nothing sends until you approve it."
          />
        ) : (
          <ul className="divide-y divide-ink-200/60">
            {rows.map((c) => (
              <li key={c.id} className="px-5 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm text-ink-900">{c.name}</span>
                      <Badge value={c.status} />
                    </div>
                    <p className="mt-1 text-xs text-ink-500">{c.subject}</p>
                    {c.validated_at ? (
                      <p className="mt-2 text-2xs text-ink-500">
                        {c.eligible_count} will be sent ·{" "}
                        {c.invalid_count + c.suppressed_count} will not ·{" "}
                        {formatUsd(
                          c.actual_charge_usd ?? c.estimated_charge_usd,
                        )}
                      </p>
                    ) : (
                      <p className="mt-2 text-2xs text-amber-700">
                        Not validated yet
                      </p>
                    )}
                    {c.sent_count > 0 && (
                      <p className="mt-1 text-2xs text-ink-500">
                        {c.delivered_count} delivered · {c.opened_count} opened
                        · {c.bounced_count} bounced
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
                    {!c.validated_at && (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={validate.isPending}
                        onClick={() => validate.mutate(c.id)}
                      >
                        Validate
                      </Button>
                    )}
                    {c.validated_at && !c.consent_confirmed_at && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => void act(c.id, "approve")}
                      >
                        I have consent
                      </Button>
                    )}
                    {c.consent_confirmed_at && c.status !== "running" && (
                      <Button
                        size="sm"
                        onClick={() => void act(c.id, "launch")}
                      >
                        Launch
                      </Button>
                    )}
                    {c.status === "running" && (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => void act(c.id, "send-batch")}
                        >
                          Send batch
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void act(c.id, "pause")}
                        >
                          Pause
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="New campaign"
        description="Created as a draft. Nothing sends yet."
      >
        <div className="space-y-4">
          <Field
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Field
            label="From"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder="hello@yourdomain.com"
          />
          <Field
            label="Subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
          <TextArea
            label="Message"
            rows={6}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <Button
            className="w-full"
            disabled={!name || !subject || !body || !from || create.isPending}
            onClick={() => {
              create.mutate({
                name,
                subject,
                text_body: body,
                from_address: from,
              });
              setName("");
              setSubject("");
              setBody("");
            }}
          >
            {create.isPending ? "Saving…" : "Create draft"}
          </Button>
          <p className="rounded-xl bg-ink-50 px-3.5 py-3 text-2xs leading-relaxed text-ink-600">
            You will be asked to confirm you have permission to email this list.
            Sending to people who did not ask is what gets a domain blocked.
          </p>
        </div>
      </Card>
    </div>
  );
}

// --- history ----------------------------------------------------------

function History() {
  const [page, setPage] = useState(1);
  const messages = useEmailMessages(page);

  return (
    <Card
      title="Delivery reports"
      description="Every email and what became of it."
      flush
    >
      <div className="px-5">
        {!messages.data?.items.length ? (
          <EmptyState title="No emails yet" />
        ) : (
          <>
            <Table
              headers={["When", "To", "Subject", "Status", "Charge", "Detail"]}
            >
              {messages.data.items.map((m) => (
                <tr key={m.id}>
                  <td className="whitespace-nowrap text-ink-500">
                    {formatDateTime(m.created_at)}
                  </td>
                  <td className="font-mono text-2xs">{m.to_address}</td>
                  <td className="max-w-xs truncate">{m.subject}</td>
                  <td>
                    <Badge value={m.status} />
                  </td>
                  <td className="tabular-nums">
                    {formatUsd(m.customer_charge_usd)}
                  </td>
                  <td className="max-w-xs truncate text-xs text-ink-500">
                    {m.error_message ?? ""}
                  </td>
                </tr>
              ))}
            </Table>
            <Pager
              page={messages.data.page}
              pages={messages.data.pages}
              total={messages.data.total}
              onChange={setPage}
            />
          </>
        )}
      </div>
    </Card>
  );
}

// --- blocked ----------------------------------------------------------

function Blocked() {
  const [page, setPage] = useState(1);
  const suppressions = useEmailSuppressions(page);
  const remove = useRemoveEmailSuppression();
  const [error, setError] = useState<string | null>(null);

  return (
    <Card
      title="Blocked addresses"
      description="Bounces, complaints and unsubscribes. These are never emailed again."
      flush
    >
      <div className="px-5">
        {error && <Alert tone="error">{error}</Alert>}
        {!suppressions.data?.items.length ? (
          <EmptyState
            title="Nothing blocked"
            hint="Addresses that bounce or unsubscribe appear here automatically."
          />
        ) : (
          <>
            <Table headers={["Address", "Reason", "Detail", "Added", ""]}>
              {suppressions.data.items.map((s) => {
                const permanent =
                  s.reason === "hard_bounce" || s.reason === "complaint";
                return (
                  <tr key={s.id}>
                    <td className="font-mono text-2xs">{s.address}</td>
                    <td>
                      <Badge value={s.reason} />
                    </td>
                    <td className="max-w-xs truncate text-xs text-ink-500">
                      {s.detail ?? ""}
                    </td>
                    <td className="whitespace-nowrap text-ink-500">
                      {formatDateTime(s.created_at)}
                    </td>
                    <td className="text-right">
                      {permanent ? (
                        <span
                          className="text-2xs text-ink-400"
                          title="Emailing an address that bounced risks your sending domain"
                        >
                          Permanent
                        </span>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            setError(null);
                            try {
                              await remove.mutateAsync(s.id);
                            } catch (err) {
                              setError(
                                (err as Error)?.message ?? "Could not unblock",
                              );
                            }
                          }}
                        >
                          Unblock
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </Table>
            <Pager
              page={suppressions.data.page}
              pages={suppressions.data.pages}
              total={suppressions.data.total}
              onChange={setPage}
            />
          </>
        )}
      </div>
    </Card>
  );
}
