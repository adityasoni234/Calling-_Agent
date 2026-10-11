import { useState } from "react";

import { usePlatformMessages } from "@/admin/hooks";
import { Empty, Grid, Metric, PageTitle, Panel, Pill } from "@/admin/ui";

/**
 * Every SMS and WhatsApp message, across every customer.
 *
 * The totals come from the server rather than being summed from the rows,
 * because the rows are truncated: adding up a capped list and labelling it
 * a total is how a dashboard quietly under-reports once a tenant gets busy.
 */

const money = (value: string) => {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n) || n === 0) return "$0.00";
  return `$${n.toFixed(Math.abs(n) < 0.01 ? 6 : 2).replace(/(\.\d*?)0+$/, "$1")}`;
};

const when = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

const CHANNELS = ["", "sms", "whatsapp"];
const STATUSES = [
  "",
  "delivered",
  "sent",
  "failed",
  "undelivered",
  "suppressed",
];

export function Messages() {
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const messages = usePlatformMessages(
    channel || undefined,
    status || undefined,
  );
  const data = messages.data;

  const margin =
    data && Number.parseFloat(data.charged_30d_usd) > 0
      ? ((Number.parseFloat(data.charged_30d_usd) -
          Number.parseFloat(data.provider_cost_30d_usd)) /
          Number.parseFloat(data.charged_30d_usd)) *
        100
      : null;

  const pill = (value: string, active: string, set: (v: string) => void) => (
    <button
      key={value || "all"}
      type="button"
      onClick={() => set(value)}
      className={`rounded-md px-2 py-1 text-[0.7rem] font-medium transition-colors ${
        active === value
          ? "bg-slate-100 text-slate-950"
          : "border border-slate-700 text-slate-400 hover:bg-slate-800"
      }`}
    >
      {value || "All"}
    </button>
  );

  return (
    <div>
      <PageTitle
        title="Messages"
        description="SMS and WhatsApp across every customer, with what each one earned."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-4">
        <Metric
          label="Messages, 30 days"
          value={String(data?.messages_30d ?? 0)}
          sub={`${data?.items.length ?? 0} shown`}
        />
        <Metric
          label="Charged"
          value={money(data?.charged_30d_usd ?? "0")}
          tone="good"
        />
        <Metric
          label="Provider cost"
          value={money(data?.provider_cost_30d_usd ?? "0")}
        />
        <Metric
          label="Delivery rate"
          value={
            data?.delivery_rate === null ? "—" : `${data?.delivery_rate ?? 0}%`
          }
          sub={
            margin === null
              ? "Of attempted sends"
              : `${margin.toFixed(0)}% margin · of attempted sends`
          }
          tone={
            data?.delivery_rate != null && data.delivery_rate < 85
              ? "bad"
              : "good"
          }
        />
      </div>

      <Panel
        title="All messages"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {CHANNELS.map((c) => pill(c, channel, setChannel))}
            <span className="mx-1 w-px bg-slate-700" />
            {STATUSES.map((s) => pill(s, status, setStatus))}
          </div>
        }
      >
        {messages.isPending ? (
          <Empty title="Loading…" />
        ) : !data?.items.length ? (
          <Empty
            title="No messages"
            hint={
              channel || status
                ? "Nothing matches those filters."
                : "Nobody has sent a message yet."
            }
          />
        ) : (
          <Grid
            headers={[
              "When",
              "Customer",
              "To",
              "Channel",
              "Status",
              "Parts",
              "Charged",
              "Detail",
            ]}
          >
            {data.items.map((m) => (
              <tr key={m.id} className="text-slate-300">
                <td className="whitespace-nowrap py-2.5 pl-4 pr-3 text-[0.7rem] text-slate-500">
                  {when(m.created_at)}
                </td>
                <td className="px-3 text-slate-100">{m.organization}</td>
                <td className="px-3 font-mono text-[0.7rem]">{m.to_number}</td>
                <td className="px-3">
                  <Pill value={m.channel} />
                </td>
                <td className="px-3">
                  <Pill value={m.status} />
                </td>
                <td className="px-3 tabular-nums">{m.segments}</td>
                <td className="px-3 tabular-nums">
                  {money(m.customer_charge_usd)}
                  {m.cost_incomplete && (
                    <span className="ml-1 text-[0.6rem] text-amber-400">
                      cost incomplete
                    </span>
                  )}
                </td>
                <td className="max-w-xs truncate px-3 text-[0.7rem] text-slate-500">
                  {m.error_message ?? m.body}
                </td>
              </tr>
            ))}
          </Grid>
        )}
      </Panel>
    </div>
  );
}
