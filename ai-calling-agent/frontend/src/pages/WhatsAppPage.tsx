import { useState } from "react";

import {
  Campaigns,
  History,
  Inbox,
  SendPanel,
  Tabs,
} from "@/components/messaging/shared";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { Select, TextArea } from "@/components/ui/Inputs";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState } from "@/components/ui/Table";
import {
  useConversations,
  useCreateTemplate,
  useDeleteTemplate,
  useMessagingReadiness,
  useSubmitTemplate,
  useSyncTemplates,
  useTemplates,
} from "@/hooks/api";
import { formatDateTime } from "@/lib/format";

/**
 * WhatsApp.
 *
 * Separate from SMS because almost everything about sending is different:
 * a message outside the 24-hour session window needs a template approved by
 * Meta, approval takes days, and the categories carry their own rejection
 * rules. The setup tab exists because every one of those is a condition that
 * otherwise surfaces as a failed send with a provider error that does not
 * say which of four causes it was.
 */

const TABS = [
  { key: "send", label: "Send" },
  { key: "inbox", label: "Conversations" },
  { key: "templates", label: "Templates" },
  { key: "campaigns", label: "Campaigns" },
  { key: "history", label: "Delivery reports" },
  { key: "setup", label: "Setup" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** Meta's own categories. The wrong one is refused on sight. */
const CATEGORIES = [
  { value: "UTILITY", label: "Utility — order updates, reminders, receipts" },
  {
    value: "MARKETING",
    label: "Marketing — offers, promotions, re-engagement",
  },
  { value: "AUTHENTICATION", label: "Authentication — one-time codes" },
] as const;

export function WhatsAppPage() {
  const [tab, setTab] = useState<TabKey>("send");
  const readiness = useMessagingReadiness();
  const templates = useTemplates("whatsapp");
  const conversations = useConversations("whatsapp");

  const unread = (conversations.data?.items ?? []).reduce(
    (total, c) => total + c.unread_count,
    0,
  );
  const approved = (templates.data ?? []).filter(
    (t) => t.status === "approved",
  );
  const pending = (templates.data ?? []).filter((t) => t.status === "pending");
  const ready = readiness.data?.whatsapp.ready ?? false;

  return (
    <div className="space-y-8">
      <PageHeader
        title="WhatsApp"
        description="Free-form replies work for 24 hours after someone messages you. Anything else needs a template Meta has approved."
      />

      {!ready && readiness.data && (
        <Alert tone="warning">
          <strong className="font-medium">WhatsApp cannot send yet.</strong>{" "}
          <button
            type="button"
            onClick={() => setTab("setup")}
            className="underline underline-offset-2"
          >
            See what is missing
          </button>
        </Alert>
      )}

      <Tabs
        tabs={TABS.map((t) => {
          if (t.key === "inbox" && unread) return { ...t, badge: unread };
          if (t.key === "templates" && pending.length)
            return { ...t, badge: pending.length };
          return t;
        })}
        active={tab}
        onChange={setTab}
      />

      {tab === "send" && (
        <SendPanel
          channel="whatsapp"
          templates={approved}
          templateId={undefined}
          onTemplate={() => {}}
          note={
            approved.length === 0 ? (
              <Alert tone="info">
                No approved templates yet, so you can only reply to people who
                messaged you in the last 24 hours. Their threads show &ldquo;can
                reply freely&rdquo; in Conversations.
              </Alert>
            ) : undefined
          }
        />
      )}
      {tab === "inbox" && <Inbox channel="whatsapp" />}
      {tab === "templates" && <Templates />}
      {tab === "campaigns" && <Campaigns channel="whatsapp" />}
      {tab === "history" && <History channel="whatsapp" />}
      {tab === "setup" && <Setup />}
    </div>
  );
}

// --- templates --------------------------------------------------------

function Templates() {
  const templates = useTemplates("whatsapp");
  const create = useCreateTemplate();
  const remove = useDeleteTemplate();
  const submit = useSubmitTemplate();
  const sync = useSyncTemplates();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState("UTILITY");
  const [error, setError] = useState<string | null>(null);
  const [showGuide, setShowGuide] = useState(false);

  const send = async (id: string) => {
    setError(null);
    try {
      await submit.mutateAsync({ id, category });
    } catch (err) {
      setError((err as Error)?.message ?? "Could not submit that template");
    }
  };

  const rows = templates.data ?? [];

  return (
    // items-start, or the grid stretches the shorter card to match the taller
    // one and leaves a half-screen of empty white inside it.
    <div className="grid items-start gap-5 xl:grid-cols-[1fr_22rem]">
      <Card
        title="Your templates"
        description="Approved by Meta, not by us. Submit a draft and Meta answers within hours to a few days."
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
        {error && (
          <div className="px-5 pt-4">
            <Alert tone="error">{error}</Alert>
          </div>
        )}
        {!rows.length ? (
          <EmptyState
            title="No templates yet"
            hint="Write one on the right, then submit it for approval."
          />
        ) : (
          // A list, not a table: a template is mostly body text, and a fixed
          // column grid either truncates it or wastes the row.
          <ul className="divide-y divide-ink-200/60">
            {rows.map((t) => (
              <li key={t.id} className="px-5 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm text-ink-900">
                        {t.name}
                      </span>
                      <Badge value={t.status} />
                      {t.placeholder_count > 0 && (
                        <span className="text-2xs text-ink-400">
                          {t.placeholder_count} variable
                          {t.placeholder_count === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                      {t.body}
                    </p>
                    <p className="mt-1.5 text-2xs text-ink-400">
                      {t.status === "pending"
                        ? "Waiting on Meta"
                        : t.status === "draft"
                          ? "Not submitted yet"
                          : `Updated ${formatDateTime(t.created_at)}`}
                    </p>
                    {t.rejection_reason && (
                      <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-2xs leading-relaxed text-red-800">
                        {t.rejection_reason}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {t.status !== "approved" && (
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
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="New template"
        description="Saved as a draft. Submit when the wording is right."
      >
        <div className="space-y-4">
          <Select
            label="Category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
          <Field
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="appointment_reminder"
          />
          <TextArea
            label="Body"
            rows={4}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            hint="Use {{1}}, {{2}} for the parts that change."
          />
          <Button
            className="w-full"
            disabled={!name || !body || create.isPending}
            onClick={() => {
              create.mutate({ name, channel: "whatsapp", body });
              setName("");
              setBody("");
            }}
          >
            {create.isPending ? "Saving…" : "Save draft"}
          </Button>

          {/* Collapsed by default. The guidance matters, but it is reference
              material and pushed the form itself below the fold. */}
          <button
            type="button"
            onClick={() => setShowGuide((open) => !open)}
            className="flex w-full items-center justify-between rounded-xl bg-ink-50 px-3.5 py-2.5 text-left text-2xs font-medium text-ink-700 transition-colors hover:bg-ink-100"
          >
            What Meta approves
            <span aria-hidden className="text-ink-400">
              {showGuide ? "−" : "+"}
            </span>
          </button>
          {showGuide && (
            <div className="space-y-3 rounded-xl bg-ink-50 px-3.5 py-3 text-2xs leading-relaxed text-ink-600">
              <div>
                <p className="font-medium text-ink-800">This passes</p>
                <p className="mt-1 font-mono text-ink-700">
                  Hi {"{{1}}"}, your consultation is confirmed for {"{{2}}"}.
                  Reply RESCHEDULE to change it.
                </p>
              </div>
              <div>
                <p className="font-medium text-ink-800">These are refused</p>
                <ul className="mt-1 space-y-1">
                  <li>
                    Vague wording like &ldquo;we have an update for you&rdquo;
                  </li>
                  <li>A sales pitch submitted under Utility</li>
                  <li>Placeholders at the very start or end</li>
                  <li>Two placeholders next to each other</li>
                </ul>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

// --- setup ------------------------------------------------------------

function Setup() {
  const readiness = useMessagingReadiness();
  const data = readiness.data;

  const steps = [
    {
      title: "Connect a WhatsApp sender",
      done: !(data?.whatsapp.blockers ?? []).some((b) =>
        b.toLowerCase().includes("sender"),
      ),
      detail:
        "WhatsApp uses a different number from your voice calls. For testing, Twilio's shared sandbox works immediately. For production you need a number registered to a WhatsApp Business Account.",
    },
    {
      title: "Get a template approved",
      done: (data?.templates.approved ?? 0) > 0,
      detail:
        "Meta reviews every template. Until one is approved you can only reply inside the 24-hour window after someone messages you.",
    },
    {
      title: "Publish a price",
      done: !(data?.unpriced_channels ?? []).includes("whatsapp"),
      detail:
        "Without a published rate, messages send but bill nothing — which is only noticed in a monthly margin report.",
    },
  ];

  return (
    <div className="grid items-start gap-5 lg:grid-cols-2">
      <Card
        title="Setup"
        description="Everything WhatsApp needs before it can send."
      >
        <ol className="space-y-5">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-3.5">
              <span
                className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-2xs font-medium ${
                  step.done
                    ? "bg-brand-700 text-white"
                    : "bg-ink-100 text-ink-500 ring-1 ring-ink-200"
                }`}
              >
                {step.done ? "✓" : index + 1}
              </span>
              <div>
                <p
                  className={`text-sm ${step.done ? "text-ink-400 line-through" : "text-ink-900"}`}
                >
                  {step.title}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-ink-500">
                  {step.detail}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </Card>

      <Card
        title="Test it today, without waiting"
        description="Meta approval takes days. The sandbox does not."
      >
        <ol className="space-y-3 text-sm leading-relaxed text-ink-700">
          <li>
            <span className="font-medium text-ink-900">1.</span> From your own
            phone, send a WhatsApp message to{" "}
            <span className="font-mono text-ink-900">+1 415 523 8886</span>.
          </li>
          <li>
            <span className="font-medium text-ink-900">2.</span> The message
            must be <span className="font-mono">join &lt;your-code&gt;</span> —
            find the code in the Twilio console under Messaging → Try it out →
            WhatsApp.
          </li>
          <li>
            <span className="font-medium text-ink-900">3.</span> You now have a
            24-hour window. Send to your own number from the Send tab with no
            template.
          </li>
        </ol>
        <p className="mt-4 rounded-xl bg-ink-50 px-4 py-3 text-xs leading-relaxed text-ink-600">
          The sandbox cannot host your own templates — it has its own fixed set.
          Custom templates need a WhatsApp Business Account, which is the step
          that takes days.
        </p>
      </Card>
    </div>
  );
}
