import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { TextArea } from "@/components/ui/Inputs";
import { EmptyState, Pager, Table } from "@/components/ui/Table";
import {
  useAddSuppression,
  useControlMessageCampaign,
  useConversations,
  useCreateMessageCampaign,
  useEstimateSend,
  useMarkConversationRead,
  useMessageCampaigns,
  useMessages,
  useRemoveSuppression,
  useSendMessage,
  useSuppressions,
} from "@/hooks/api";
import { formatDateTime, formatUsd } from "@/lib/format";
import { STATUS_HELP } from "@/components/messaging/status";
import type { Channel, MessageTemplate } from "@/types/api";

/**
 * The parts of SMS and WhatsApp that genuinely are the same.
 *
 * The two channels have their own pages because they are not the same
 * product -- WhatsApp has templates, Meta approval and a 24-hour session
 * window, and SMS has segments and a per-part bill. But a thread is a
 * thread and an opt-out is an opt-out, so those live here once rather than
 * being copied and allowed to drift.
 *
 * Every component takes the channel and filters by it, so neither page can
 * ever show the other's messages.
 */

// --- conversations ----------------------------------------------------

export function Inbox({ channel }: { channel: Channel }) {
  const conversations = useConversations(channel);
  const markRead = useMarkConversationRead();
  const [openId, setOpenId] = useState<string | null>(null);
  const thread = useMessages(openId ? { conversation_id: openId } : {}, 1);

  const items = conversations.data?.items ?? [];
  const open = items.find((c) => c.id === openId);

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[21rem_1fr]">
      <Card
        title="Threads"
        description="Newest first. Replies land in the same thread."
        flush
      >
        {conversations.isPending ? (
          <div className="space-y-2 p-5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-14 rounded-xl" />
            ))}
          </div>
        ) : !items.length ? (
          <EmptyState
            title="No conversations yet"
            hint="Threads appear here once you send a message or receive a reply."
          />
        ) : (
          <ul className="divide-y divide-ink-200/60">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => {
                    setOpenId(item.id);
                    if (item.unread_count > 0) markRead.mutate(item.id);
                  }}
                  className={`w-full px-5 py-3.5 text-left transition-colors hover:bg-ink-50 ${
                    openId === item.id ? "bg-ink-50" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-ink-900">
                      {item.contact_name ?? item.contact_number}
                    </span>
                    {item.unread_count > 0 && (
                      <span className="rounded-full bg-brand-700 px-1.5 py-0.5 text-2xs font-medium text-white">
                        {item.unread_count}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-2xs text-ink-400">
                    <span>{formatDateTime(item.last_message_at)}</span>
                    {channel === "whatsapp" && item.session_open && (
                      <span className="text-brand-700">· can reply freely</span>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title={
          open
            ? (open.contact_name ?? open.contact_number)
            : "Pick a conversation"
        }
        description={
          !open
            ? "Select a thread on the left to read it."
            : channel === "whatsapp" && !open.session_open
              ? "Outside the 24-hour window — a reply needs an approved template."
              : "Most recent messages first."
        }
      >
        {!openId ? (
          <EmptyState
            title="Nothing selected"
            hint="Choose a thread to read the messages."
          />
        ) : !thread.data?.items.length ? (
          <EmptyState title="No messages in this thread" />
        ) : (
          <ul className="space-y-3">
            {thread.data.items.map((message) => (
              <li
                key={message.id}
                className={`max-w-lg rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  message.direction === "inbound"
                    ? "bg-ink-100 text-ink-800"
                    : "ml-auto bg-brand-700 text-white"
                }`}
              >
                <p className="whitespace-pre-wrap">{message.body}</p>
                <p
                  className={`mt-1.5 text-2xs ${
                    message.direction === "inbound"
                      ? "text-ink-400"
                      : "text-white/60"
                  }`}
                >
                  {formatDateTime(message.created_at)} · {message.status}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// --- sending ----------------------------------------------------------

export function SendPanel({
  channel,
  templates,
  templateId,
  onTemplate,
  note,
}: {
  channel: Channel;
  templates?: MessageTemplate[];
  templateId?: string;
  onTemplate?: (id: string) => void;
  note?: React.ReactNode;
}) {
  const [recipients, setRecipients] = useState("");
  const [body, setBody] = useState("");
  const estimate = useEstimateSend();
  const send = useSendMessage();
  const [result, setResult] = useState<string | null>(null);

  const numbers = recipients
    .split(/[\s,;]+/)
    .map((n) => n.trim())
    .filter(Boolean);
  const quote = estimate.data;

  const doSend = async () => {
    setResult(null);
    let ok = 0;
    let blocked = 0;
    for (const number of numbers) {
      const sent = await send.mutateAsync({
        to_number: number,
        channel,
        body: body || undefined,
        template_id: templateId || undefined,
        idempotency_key: `ui-${number}-${Date.now()}`,
      });
      if (sent.status === "suppressed") blocked += 1;
      else ok += 1;
    }
    setResult(
      blocked
        ? `${ok} sent. ${blocked} skipped because they opted out.`
        : `${ok} message${ok === 1 ? "" : "s"} sent.`,
    );
    setRecipients("");
    setBody("");
  };

  return (
    <div className="grid items-start gap-5 lg:grid-cols-2">
      <Card
        title="Compose"
        description="One number per line, or comma separated."
      >
        <div className="space-y-4">
          {note}
          <TextArea
            label="Recipients"
            rows={4}
            value={recipients}
            placeholder={"+919876543210\n+919812345678"}
            onChange={(e) => setRecipients(e.target.value)}
            hint={`${numbers.length} number${numbers.length === 1 ? "" : "s"}`}
          />

          {templates && onTemplate && (
            <div>
              <label
                className="block text-xs font-medium text-ink-700"
                htmlFor="template-pick"
              >
                Template
              </label>
              <select
                id="template-pick"
                value={templateId ?? ""}
                onChange={(e) => onTemplate(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-ink-300/70 bg-white px-3 py-2 text-sm"
              >
                <option value="">
                  No template — reply within 24 hours only
                </option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <TextArea
            label="Message"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            hint={
              channel === "sms"
                ? "Emoji and ₹ switch the message to a shorter encoding, which costs more per message."
                : "Keep it specific. Vague wording is what gets a sender reported."
            }
          />

          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={!numbers.length || estimate.isPending}
              onClick={() =>
                estimate.mutate({
                  channel,
                  recipients: numbers,
                  body: body || undefined,
                  template_id: templateId || undefined,
                })
              }
            >
              {estimate.isPending ? "Checking…" : "Check cost"}
            </Button>
            <Button
              onClick={() => void doSend()}
              disabled={!numbers.length || send.isPending}
            >
              {send.isPending ? "Sending…" : "Send"}
            </Button>
          </div>

          {result && <Alert tone="success">{result}</Alert>}
          {send.isError && (
            <Alert tone="error">
              {(send.error as Error)?.message ?? "Could not send."}
            </Alert>
          )}
        </div>
      </Card>

      <Card
        title="What this will cost"
        description="Calculated by the server, before anything sends."
      >
        {!quote ? (
          <EmptyState
            title="No estimate yet"
            hint="Enter recipients and press Check cost to see the bill first."
          />
        ) : (
          <dl className="space-y-3 text-sm">
            <Row label="Recipients" value={String(quote.recipients)} />
            <Row
              label="Will be skipped"
              value={String(quote.suppressed)}
              hint={
                quote.suppressed > 0
                  ? "Opted out or not a valid number"
                  : undefined
              }
            />
            <Row
              label="Will be sent"
              value={String(quote.billable_recipients)}
            />
            <Row
              label={channel === "sms" ? "Segments each" : "Messages each"}
              value={String(quote.segments_per_message)}
              hint={
                quote.segments_per_message > 1
                  ? "Long or non-Latin text splits into parts, each billed separately"
                  : undefined
              }
            />
            <div className="border-t border-ink-200/60 pt-3">
              <Row
                label="You will be charged"
                value={formatUsd(quote.customer_charge_usd)}
                accent
              />
            </div>
            {quote.cost_incomplete && (
              <Alert tone="warning">
                This channel has no published price yet, so the charge shown may
                be incomplete.
              </Alert>
            )}
          </dl>
        )}
      </Card>
    </div>
  );
}

function Row({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-ink-500">
        {label}
        {hint && (
          <span className="mt-0.5 block text-2xs text-ink-400">{hint}</span>
        )}
      </dt>
      <dd
        className={`shrink-0 tabular-nums ${
          accent ? "font-display text-xl text-brand-700" : "text-ink-900"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

// --- delivery reports -------------------------------------------------

export function History({ channel }: { channel: Channel }) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const messages = useMessages(
    { channel, ...(status ? { status } : {}) },
    page,
  );

  const statuses = [
    "",
    "queued",
    "sent",
    "delivered",
    "read",
    "undelivered",
    "failed",
    "suppressed",
  ];

  return (
    <Card
      title="Delivery reports"
      description="Every message with what happened to it and what it cost."
      actions={
        <div className="flex flex-wrap gap-1.5">
          {statuses.map((s) => (
            <button
              key={s || "all"}
              type="button"
              onClick={() => {
                setStatus(s);
                setPage(1);
              }}
              className={`rounded-lg px-2 py-1 text-2xs font-medium transition-colors ${
                status === s
                  ? "bg-brand-700 text-white"
                  : "text-ink-500 ring-1 ring-ink-200 hover:bg-ink-50"
              }`}
            >
              {s || "All"}
            </button>
          ))}
        </div>
      }
      flush
    >
      <div className="px-5">
        {!messages.data?.items.length ? (
          <EmptyState
            title="No messages yet"
            hint={
              status
                ? "Nothing with that status."
                : "Sent and received messages appear here."
            }
          />
        ) : (
          <>
            <Table
              headers={["When", "To", "Status", "Parts", "Charge", "Detail"]}
            >
              {messages.data.items.map((m) => (
                <tr key={m.id}>
                  <td className="whitespace-nowrap text-ink-500">
                    {formatDateTime(m.created_at)}
                  </td>
                  <td className="font-mono text-2xs">{m.to_number}</td>
                  <td>
                    <Badge value={m.status} />
                  </td>
                  <td className="tabular-nums">{m.segments}</td>
                  <td className="tabular-nums">
                    {formatUsd(m.customer_charge_usd)}
                  </td>
                  <td className="max-w-xs truncate text-xs text-ink-500">
                    {m.error_message ?? STATUS_HELP[m.status] ?? ""}
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

// --- campaigns --------------------------------------------------------

const CAMPAIGN_ACTIONS: Record<string, string[]> = {
  draft: ["launch"],
  scheduled: ["send-now", "cancel"],
  running: ["send-now", "pause", "cancel"],
  paused: ["resume", "cancel"],
  failed: ["resume", "cancel"],
};

export function Campaigns({ channel }: { channel: Channel }) {
  const campaigns = useMessageCampaigns();
  const create = useCreateMessageCampaign();
  const control = useControlMessageCampaign();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const rows = (campaigns.data ?? []).filter((c) => c.channel === channel);

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[1fr_21rem]">
      <Card
        title="Campaigns"
        description="Each recipient goes through the same opt-out and pricing checks as a single send."
        flush
      >
        <div className="px-5">
          {!rows.length ? (
            <EmptyState
              title="No campaigns yet"
              hint="Create one on the right. You will see the cost before anything sends."
            />
          ) : (
            <Table
              headers={[
                "Campaign",
                "Status",
                "Progress",
                "Sent",
                "Skipped",
                "Cost",
                "",
              ]}
            >
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <p className="text-ink-900">{c.name}</p>
                    <p className="mt-0.5 text-2xs text-ink-500">
                      {c.total_recipients} recipients
                    </p>
                  </td>
                  <td>
                    <Badge value={c.status} />
                  </td>
                  <td className="w-32">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-200">
                      <div
                        className="h-full rounded-full bg-brand-700 transition-all"
                        style={{ width: `${c.percent_complete}%` }}
                      />
                    </div>
                    <span className="mt-1 block text-2xs tabular-nums text-ink-400">
                      {c.percent_complete}%
                    </span>
                  </td>
                  <td className="tabular-nums">
                    {c.sent_count}
                    {c.delivered_count > 0 && (
                      <span className="ml-1 text-2xs text-brand-700">
                        {c.delivered_count} delivered
                      </span>
                    )}
                  </td>
                  <td className="tabular-nums text-ink-500">
                    {c.suppressed_count}
                  </td>
                  <td className="tabular-nums">
                    {formatUsd(c.actual_charge_usd ?? c.estimated_charge_usd)}
                    {!c.actual_charge_usd && (
                      <span className="ml-1 text-2xs text-ink-400">est.</span>
                    )}
                  </td>
                  <td className="text-right">
                    <div className="flex justify-end gap-1">
                      {(CAMPAIGN_ACTIONS[c.status] ?? []).map((action) => (
                        <Button
                          key={action}
                          size="sm"
                          variant={action === "cancel" ? "ghost" : "secondary"}
                          disabled={control.isPending}
                          onClick={() => control.mutate({ id: c.id, action })}
                        >
                          {action === "send-now" ? "Send batch" : action}
                        </Button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Card>

      <Card
        title="New campaign"
        description="Sends to every lead with a phone number. You see the cost before launching."
      >
        <div className="space-y-4">
          <Field
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="October follow-up"
          />
          <TextArea
            label="Message"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <Button
            className="w-full"
            disabled={!name || !body || create.isPending}
            onClick={async () => {
              setError(null);
              try {
                await create.mutateAsync({ name, channel, body });
                setName("");
                setBody("");
              } catch (err) {
                setError(
                  (err as Error)?.message ?? "Could not create that campaign",
                );
              }
            }}
          >
            {create.isPending ? "Checking cost…" : "Create as draft"}
          </Button>
          {error && <Alert tone="error">{error}</Alert>}
          <p className="text-2xs leading-relaxed text-ink-400">
            Created as a draft with its cost attached. Nothing sends until you
            press Launch.
          </p>
        </div>
      </Card>
    </div>
  );
}

// --- opt-outs ---------------------------------------------------------

export function OptOuts() {
  const [page, setPage] = useState(1);
  const suppressions = useSuppressions(page);
  const add = useAddSuppression();
  const remove = useRemoveSuppression();
  const [number, setNumber] = useState("");

  return (
    <Card
      title="Opt-outs and DND"
      description="These numbers are never messaged on any channel. The block is enforced on the server, not in this screen."
      actions={
        <div className="flex gap-2">
          <input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="+919876543210"
            className="rounded-xl border border-ink-300/70 px-2.5 py-1.5 text-xs"
          />
          <Button
            size="sm"
            disabled={!number || add.isPending}
            onClick={() => {
              add.mutate({ contact_number: number, reason: "manual" });
              setNumber("");
            }}
          >
            Add
          </Button>
        </div>
      }
      flush
    >
      <div className="px-5">
        {add.isError && (
          <Alert tone="error">
            {(add.error as Error)?.message ?? "Could not add that number."}
          </Alert>
        )}
        {!suppressions.data?.items.length ? (
          <EmptyState
            title="Nobody has opted out"
            hint="Numbers added here, or that reply STOP, are never messaged again."
          />
        ) : (
          <>
            <Table headers={["Number", "Channel", "Reason", "Added", ""]}>
              {suppressions.data.items.map((s) => (
                <tr key={s.id}>
                  <td className="font-mono text-2xs">{s.contact_number}</td>
                  <td>{s.channel ?? "All"}</td>
                  <td>
                    <Badge value={s.reason} />
                  </td>
                  <td className="whitespace-nowrap text-ink-500">
                    {formatDateTime(s.created_at)}
                  </td>
                  <td className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => remove.mutate(s.id)}
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
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

// --- tabs -------------------------------------------------------------

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly { key: T; label: string; badge?: number }[];
  active: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5 border-b border-ink-200/60 pb-px">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors ${
            active === tab.key
              ? "border-brand-700 text-ink-900"
              : "border-transparent text-ink-500 hover:text-ink-800"
          }`}
        >
          {tab.label}
          {tab.badge ? (
            <span className="rounded-full bg-brand-700 px-1.5 py-px text-2xs font-medium text-white">
              {tab.badge}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
