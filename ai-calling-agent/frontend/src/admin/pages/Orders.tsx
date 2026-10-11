import { useState } from "react";

import {
  useAdminOrders,
  useRetryAllocation,
  useUnallocatedOrders,
} from "@/admin/hooks";
import {
  Action,
  Empty,
  Grid,
  Metric,
  PageTitle,
  Panel,
  Pill,
} from "@/admin/ui";
import type { AdminOrder } from "@/types/api";

/**
 * Every purchase on the platform.
 *
 * The page leads with stuck orders — paid, but credits never allocated —
 * because that is the only state where a customer has given us money and
 * received nothing. It should always be empty; when it is not, it is the most
 * urgent thing on the platform.
 */

const FILTERS = [
  { key: "", label: "All" },
  { key: "paid", label: "Paid" },
  { key: "pending", label: "Pending" },
  { key: "failed", label: "Failed" },
  { key: "refunded", label: "Refunded" },
] as const;

const money = (minor: number, currency = "USD") =>
  new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(minor / 100);

const when = (value: string | null) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";

export function Orders() {
  const [filter, setFilter] = useState<string>("");
  const orders = useAdminOrders(filter || undefined);
  const stuck = useUnallocatedOrders();
  const retry = useRetryAllocation();

  const rows = orders.data ?? [];
  const paid = rows.filter((o) => o.status === "paid");
  const revenue = paid.reduce((sum, o) => sum + o.total_minor, 0);
  const refunded = rows.reduce((sum, o) => sum + o.refunded_minor, 0);

  const row = (order: AdminOrder, withRetry = false) => (
    <tr key={order.id} className="text-slate-300">
      <td className="py-2.5 pl-4 pr-3 font-mono text-[0.7rem] text-slate-400">
        {order.reference}
      </td>
      <td className="px-3">
        <p className="text-slate-100">{order.organization_name}</p>
        <p className="text-[0.65rem] text-slate-500">{order.package_name}</p>
      </td>
      <td className="whitespace-nowrap px-3 tabular-nums">
        {money(order.total_minor, order.currency)}
        {order.refunded_minor > 0 && (
          <span className="ml-1 text-[0.65rem] text-violet-400">
            −{money(order.refunded_minor, order.currency)}
          </span>
        )}
      </td>
      <td className="px-3 tabular-nums">
        {order.credits_allocated_at ? (
          order.total_credits.toLocaleString()
        ) : order.status === "paid" ? (
          // Only alarming once they have paid. An unpaid order has no credits
          // by definition, and colouring that amber cries wolf.
          <span className="text-amber-400">not allocated</span>
        ) : (
          "—"
        )}
      </td>
      <td className="px-3">
        <Pill value={order.status} />
      </td>
      <td className="px-3 text-[0.7rem] text-slate-500">
        {order.provider ?? "—"}
        {order.provider_payment_id && (
          <span className="block font-mono text-[0.65rem]">
            {order.provider_payment_id}
          </span>
        )}
      </td>
      <td className="whitespace-nowrap px-3 text-[0.7rem] text-slate-500">
        {when(order.paid_at ?? order.created_at)}
      </td>
      {withRetry && (
        <td className="px-3">
          <Action
            tone="primary"
            busy={retry.isPending}
            onClick={() => void retry.mutateAsync(order.id)}
          >
            Allocate now
          </Action>
        </td>
      )}
    </tr>
  );

  return (
    <div>
      <PageTitle
        title="Orders"
        description="Every purchase, with the provider's own payment reference."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-4">
        <Metric
          label="Paid orders"
          value={String(paid.length)}
          sub={`${rows.length} shown`}
        />
        <Metric label="Revenue" value={money(revenue)} tone="good" />
        <Metric
          label="Refunded"
          value={money(refunded)}
          tone={refunded > 0 ? "bad" : "neutral"}
        />
        <Metric
          label="Credits not allocated"
          value={String(stuck.data?.length ?? 0)}
          sub="Paid but nothing granted"
          tone={stuck.data?.length ? "bad" : "good"}
        />
      </div>

      {!!stuck.data?.length && (
        <div className="mb-5">
          <Panel
            title="Paid, but credits never landed"
            description="These customers have paid and received nothing. Allocation is idempotent, so retrying is safe."
          >
            <Grid
              headers={[
                "Reference",
                "Customer",
                "Amount",
                "Credits",
                "Status",
                "Provider",
                "Paid",
                "",
              ]}
            >
              {stuck.data.map((order) => row(order, true))}
            </Grid>
          </Panel>
        </div>
      )}

      <Panel
        title="All orders"
        actions={
          <div className="flex gap-1.5">
            {FILTERS.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setFilter(option.key)}
                className={`rounded-md px-2 py-1 text-[0.7rem] font-medium transition-colors ${
                  filter === option.key
                    ? "bg-slate-100 text-slate-950"
                    : "border border-slate-700 text-slate-400 hover:bg-slate-800"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      >
        {orders.isPending ? (
          <Empty title="Loading…" />
        ) : !rows.length ? (
          <Empty
            title="No orders"
            hint={
              filter
                ? "Nothing with that status."
                : "No one has bought credits yet."
            }
          />
        ) : (
          <Grid
            headers={[
              "Reference",
              "Customer",
              "Amount",
              "Credits",
              "Status",
              "Provider",
              "When",
            ]}
          >
            {rows.map((order) => row(order))}
          </Grid>
        )}
      </Panel>
    </div>
  );
}
