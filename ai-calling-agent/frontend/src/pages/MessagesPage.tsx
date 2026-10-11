import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { Select, TextArea } from "@/components/ui/Inputs";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState, Pager, Table } from "@/components/ui/Table";
import {
  useAddSuppression,
  useControlMessageCampaign,
  useCreateMessageCampaign,
  useMessageCampaigns,
  useConversations,
  useCreateTemplate,
  useDeleteTemplate,
  useEstimateSend,
  useMarkConversationRead,
  useMessages,
  useRemoveSuppression,
  useSendMessage,
  useSubmitTemplate,
  useSyncTemplates,
  useSuppressions,
  useTemplates,
} from "@/hooks/api";
import { formatDateTime, formatUsd } from "@/lib/format";
import type { Channel } from "@/types/api";

/**
 * SMS and WhatsApp.
 *
 * One page with tabs rather than five sidebar entries: sending, reading
 * replies and managing opt-outs are the same job, and splitting them meant
 * three clicks to answer one message.
 *
 * Nothing here computes a price. The estimate and the charge both come from
 * the server, because a price a browser can calculate is a price a customer
 * can change.
 */

const TABS = [
  { key: "inbox", label: "Conversations" },
  { key: "send", label: "Send" },
  { key: "campaigns", label: "Campaigns" },
  { key: "history", label: "Delivery reports" },
  { key: "templates", label: "Templates" },
  { key: "optouts", label: "Opt-outs" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** Why a message ended where it did, in words a non-technical user can act on. */
const STATUS_HELP: Record<string, string> = {
  suppressed: "Blocked — this contact opted out",
  undelivered: "The carrier accepted it but could not deliver it",
  failed: "Rejected before sending",
  queued: "Waiting to be sent",
  sent: "Handed to the carrier",
  delivered: "Confirmed delivered",
  read: "Opened by the recipient",
};

export function MessagesPage() {
  const [tab, setTab] = useState<TabKey>("inbox");
  const [channel, setChannel] = useState<Channel>("sms");

  return (
    <div className="space-y-8">
      <PageHeader
        title="Messages"
        description="SMS and WhatsApp. Charges are per segment, and opted-out contacts are never messaged."
      />

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

      {tab === "inbox" && <Inbox />}
      {tab === "send" && <SendPanel channel={channel} onChannel={setChannel} />}
      {tab === "campaigns" && <Campaigns />}
      {tab === "history" && <History />}
      {tab === "templates" && <Templates />}
      {tab === "optouts" && <OptOuts />}
    </div>
  );
}

// --- conversations ----------------------------------------------------

function Inbox() {
  const conversations = useConversations();
  const markRead = useMarkConversationRead();
  const [openId, setOpenId] = useState<string | null>(null);
  const thread = useMessages(openId ? { conversation_id: openId } : {}, 1);

  const items = conversations.data?.items ?? [];

  return (
    <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
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
                  <div className="mt-1 flex items-center gap-2">
                    <Badge value={item.channel} />
                    <span className="text-2xs text-ink-400">
                      {formatDateTime(item.last_message_at)}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title={openId ? "Thread" : "Pick a conversation"}
        description={
          openId
            ? items.find((c) => c.id === openId)?.channel === "whatsapp" &&
              !items.find((c) => c.id === openId)?.session_open
              ? "Outside the 24-hour window — a reply needs an approved template."
              : "Most recent messages first."
            : "Select a thread on the left to read it."
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

function SendPanel({
  channel,
  onChannel,
}: {
  channel: Channel;
  onChannel: (c: Channel) => void;
}) {
  const [recipients, setRecipients] = useState("");
  const [body, setBody] = useState("");
  const [templateId, setTemplateId] = useState("");
  const templates = useTemplates(channel);
  const estimate = useEstimateSend();
  const send = useSendMessage();
  const [sent, setSent] = useState<string | null>(null);

  const numbers = recipients
    .split(/[\s,;]+/)
    .map((n) => n.trim())
    .filter(Boolean);

  const quote = estimate.data;
  const approved = (templates.data ?? []).filter(
    (t) => t.status === "approved",
  );

  const doEstimate = () => {
    if (!numbers.length) return;
    estimate.mutate({
      channel,
      recipients: numbers,
      body: body || undefined,
      template_id: templateId || undefined,
    });
  };

  const doSend = async () => {
    setSent(null);
    let ok = 0;
    for (const number of numbers) {
      const result = await send.mutateAsync({
        to_number: number,
        channel,
        body: body || undefined,
        template_id: templateId || undefined,
        // Scoped to this batch so a double-click cannot send twice.
        idempotency_key: `ui-${number}-${body.slice(0, 20)}-${Date.now()}`,
      });
      if (result.status !== "suppressed") ok += 1;
    }
    setSent(`${ok} of ${numbers.length} queued. The rest were opted out.`);
    setRecipients("");
    setBody("");
  };

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card
        title="Compose"
        description="One number per line, or comma separated."
      >
        <div className="space-y-4">
          <Select
            label="Channel"
            value={channel}
            onChange={(e) => {
              onChannel(e.target.value as Channel);
              setTemplateId("");
            }}
          >
            <option value="sms">SMS</option>
            <option value="whatsapp">WhatsApp</option>
          </Select>

          <TextArea
            label="Recipients"
            rows={4}
            value={recipients}
            placeholder={"+919876543210\n+919812345678"}
            onChange={(e) => setRecipients(e.target.value)}
            hint={`${numbers.length} number${numbers.length === 1 ? "" : "s"}`}
          />

          {channel === "whatsapp" && (
            <Select
              label="Template"
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              hint="WhatsApp needs an approved template unless the contact messaged you in the last 24 hours."
            >
              <option value="">No template (reply within 24h only)</option>
              {approved.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </Select>
          )}

          <TextArea
            label="Message"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            hint="Emoji and ₹ switch the message to a shorter encoding, which costs more per message."
          />

          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={doEstimate}
              disabled={!numbers.length}
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

          {sent && <Alert tone="success">{sent}</Alert>}
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
              label="Segments each"
              value={String(quote.segments_per_message)}
              hint={
                quote.segments_per_message > 1
                  ? "Long or non-Latin text splits into parts, each billed separately"
                  : undefined
              }
            />
            <Row label="Total segments" value={String(quote.total_segments)} />
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
                be incomplete. Contact us before sending in bulk.
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

function History() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const messages = useMessages(status ? { status } : {}, page);

  return (
    <Card
      title="Delivery reports"
      description="Every message with what happened to it and what it cost."
      actions={
        <Select
          label=""
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          {[
            "queued",
            "sent",
            "delivered",
            "read",
            "undelivered",
            "failed",
            "suppressed",
          ].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      }
      flush
    >
      <div className="px-5">
        {!messages.data?.items.length ? (
          <EmptyState
            title="No messages yet"
            hint="Sent and received messages appear here."
          />
        ) : (
          <>
            <Table
              headers={[
                "When",
                "To",
                "Channel",
                "Status",
                "Parts",
                "Charge",
                "Detail",
              ]}
            >
              {messages.data.items.map((m) => (
                <tr key={m.id}>
                  <td className="whitespace-nowrap text-ink-500">
                    {formatDateTime(m.created_at)}
                  </td>
                  <td className="font-mono text-2xs">{m.to_number}</td>
                  <td>
                    <Badge value={m.channel} />
                  </td>
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

// --- templates --------------------------------------------------------

/** Meta's own categories. The wrong one is refused on sight. */
const CATEGORIES = [
  { value: "UTILITY", label: "Utility — order updates, reminders, receipts" },
  {
    value: "MARKETING",
    label: "Marketing — offers, promotions, re-engagement",
  },
  { value: "AUTHENTICATION", label: "Authentication — one-time codes" },
] as const;

function Templates() {
  const templates = useTemplates();
  const create = useCreateTemplate();
  const remove = useDeleteTemplate();
  const submit = useSubmitTemplate();
  const sync = useSyncTemplates();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState<Channel>("whatsapp");
  const [category, setCategory] = useState("UTILITY");
  const [error, setError] = useState<string | null>(null);

  const send = async (id: string) => {
    setError(null);
    try {
      await submit.mutateAsync({ id, category });
    } catch (err) {
      setError((err as Error)?.message ?? "Could not submit that template");
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
      <Card
        title="Your templates"
        description="WhatsApp templates are approved by Meta, not by us. Submit a draft and Meta answers within hours to a few days."
        actions={
          <Button
            size="sm"
            variant="secondary"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            {sync.isPending ? "Checking…" : "Check approvals"}
          </Button>
        }
        flush
      >
        <div className="px-5">
          {error && <Alert tone="error">{error}</Alert>}
          {!templates.data?.length ? (
            <EmptyState
              title="No templates yet"
              hint="Create one on the right, then submit it for approval."
            />
          ) : (
            <Table headers={["Name", "Channel", "Status", "Variables", ""]}>
              {templates.data.map((t) => (
                <tr key={t.id}>
                  <td>
                    <p className="text-ink-900">{t.name}</p>
                    <p className="mt-0.5 max-w-sm truncate text-2xs text-ink-500">
                      {t.body}
                    </p>
                    {t.rejection_reason && (
                      <p className="mt-1 max-w-sm text-2xs leading-relaxed text-red-700">
                        {t.rejection_reason}
                      </p>
                    )}
                  </td>
                  <td>
                    <Badge value={t.channel} />
                  </td>
                  <td>
                    <Badge value={t.status} />
                    {t.status === "pending" && (
                      <span className="mt-0.5 block text-2xs text-ink-400">
                        with Meta
                      </span>
                    )}
                  </td>
                  <td className="tabular-nums">{t.placeholder_count}</td>
                  <td className="text-right">
                    <div className="flex justify-end gap-1">
                      {t.channel === "whatsapp" && t.status !== "approved" && (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={submit.isPending || t.status === "pending"}
                          onClick={() => void send(t.id)}
                        >
                          {t.status === "pending" ? "Submitted" : "Submit"}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => remove.mutate(t.id)}
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Card>

      <Card
        title="New template"
        description="Saved as a draft. Submit it when you are happy with the wording."
      >
        <div className="space-y-4">
          <Select
            label="Channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value as Channel)}
          >
            <option value="whatsapp">WhatsApp</option>
            <option value="sms">SMS</option>
          </Select>
          {channel === "whatsapp" && (
            <Select
              label="Category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              hint="Meta refuses a promotional message submitted as Utility."
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          )}
          <Field
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="appointment_reminder"
          />
          <TextArea
            label="Body"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            hint="Use {{1}}, {{2}} for the parts that change."
          />
          <Button
            className="w-full"
            disabled={!name || !body || create.isPending}
            onClick={() => {
              create.mutate({ name, channel, body });
              setName("");
              setBody("");
            }}
          >
            {create.isPending ? "Saving…" : "Save draft"}
          </Button>
          {create.isError && (
            <Alert tone="error">
              {(create.error as Error)?.message ?? "Could not save."}
            </Alert>
          )}
          <div className="rounded-xl bg-ink-50 px-4 py-3 text-2xs leading-relaxed text-ink-600">
            <p className="font-medium text-ink-800">What Meta rejects</p>
            <ul className="mt-1.5 space-y-1">
              <li>Vague wording like "we have an update for you"</li>
              <li>Anything that reads as a cold sales pitch under Utility</li>
              <li>Placeholders at the very start or end of the message</li>
              <li>Two placeholders next to each other</li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}

// --- opt-outs ---------------------------------------------------------

function OptOuts() {
  const [page, setPage] = useState(1);
  const suppressions = useSuppressions(page);
  const add = useAddSuppression();
  const remove = useRemoveSuppression();
  const [number, setNumber] = useState("");

  return (
    <Card
      title="Opt-outs and DND"
      description="These numbers are never messaged. The block is enforced on the server, not in this screen."
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
            hint="Numbers added here, or that reply STOP, will never be messaged again."
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

// --- bulk campaigns ---------------------------------------------------

const CAMPAIGN_ACTIONS: Record<string, string[]> = {
  draft: ["launch"],
  scheduled: ["send-now", "cancel"],
  running: ["send-now", "pause", "cancel"],
  paused: ["resume", "cancel"],
  failed: ["resume", "cancel"],
};

function Campaigns() {
  const campaigns = useMessageCampaigns();
  const create = useCreateMessageCampaign();
  const control = useControlMessageCampaign();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState<Channel>("sms");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      await create.mutateAsync({ name, channel, body });
      setName("");
      setBody("");
    } catch (err) {
      setError((err as Error)?.message ?? "Could not create that campaign");
    }
  };

  const rows = campaigns.data ?? [];

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
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
                      {c.channel} · {c.total_recipients} recipients
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
        description="Sends to every lead with a phone number. You will see the cost before launching."
      >
        <div className="space-y-4">
          <Select
            label="Channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value as Channel)}
          >
            <option value="sms">SMS</option>
            <option value="whatsapp">WhatsApp</option>
          </Select>
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
            onClick={() => void submit()}
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
