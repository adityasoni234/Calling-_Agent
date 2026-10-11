import { Link, useParams } from "react-router-dom";

import { useCustomerProfile } from "@/admin/hooks";
import { money } from "@/admin/format";
import { Empty, Grid, Metric, PageTitle, Panel, Pill } from "@/admin/ui";

/**
 * One customer, everything.
 *
 * A support conversation starts with "what happened on this account", and the
 * answer spans credits, calls, agents and payments. Every figure here comes
 * from a single server-side read so the numbers cannot disagree with each
 * other halfway through an investigation.
 */

const when = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";

const dollars = (minor: number) =>
  `$${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

/** Pressing a button to launch an AI is a manual call placed in agent mode. */
const BACKFILLED = "backfilled:";

const SOURCES: Record<string, string> = {
  manual: "Manual",
  campaign: "Campaign",
  api: "API",
  inbound: "Inbound",
  scheduled: "Scheduled",
  internal: "Internal",
};

export function CustomerProfile() {
  const { id } = useParams<{ id: string }>();
  const profile = useCustomerProfile(id ?? null);

  if (profile.isPending) {
    return (
      <div>
        <PageTitle title="Customer" />
        <Empty title="Loading…" />
      </div>
    );
  }

  if (profile.isError || !profile.data) {
    return (
      <div>
        <PageTitle title="Customer" />
        <Empty
          title="Could not load this customer"
          hint={
            (profile.error as Error)?.message ??
            "The account may have been removed."
          }
        />
      </div>
    );
  }

  const p = profile.data;
  const org = p.organization;
  // Credits are cents of list price, so margin is what we sold minus what we
  // paid -- over the same thirty days on both sides.
  const margin = p.consumed_30d / 100 - p.provider_cost_30d_usd;

  return (
    <div>
      <PageTitle
        title={org.name}
        description={`${org.slug} · ${org.plan} · joined ${when(org.created_at)}`}
        actions={
          <Link
            to="/customers"
            className="whitespace-nowrap rounded-md border border-slate-700 px-2 py-1 text-[0.7rem] font-medium text-slate-300 transition-colors hover:bg-slate-800"
          >
            All customers
          </Link>
        }
      />

      {org.is_suspended && (
        <p className="mb-5 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-[0.8rem] text-red-300">
          <strong className="font-medium">Suspended.</strong>{" "}
          {org.suspended_reason ?? "No reason recorded."}
        </p>
      )}

      {!!p.unallocated_orders.length && (
        <p className="mb-5 rounded-md border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-[0.8rem] text-amber-300">
          <strong className="font-medium">
            {p.unallocated_orders.length} paid order
            {p.unallocated_orders.length === 1 ? "" : "s"} never allocated
            credits.
          </strong>{" "}
          This customer has paid and received nothing.{" "}
          <Link to="/orders" className="underline">
            Fix on the orders page
          </Link>
          .
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Spendable"
          value={p.spendable.toFixed(0)}
          sub={
            p.held > 0
              ? `${p.held.toFixed(0)} held for live calls`
              : money(p.spendable)
          }
          tone={p.spendable <= 0 ? "bad" : "neutral"}
        />
        <Metric
          label="Balance"
          value={p.balance.toFixed(0)}
          sub={money(p.balance)}
        />
        <Metric
          label="Paid us"
          value={dollars(p.paid_minor)}
          sub={`${p.paid_orders} order${p.paid_orders === 1 ? "" : "s"}${
            p.refunded_minor ? ` · ${dollars(p.refunded_minor)} refunded` : ""
          }`}
          tone="good"
        />
        <Metric
          label="Margin, 30 days"
          value={`$${margin.toFixed(2)}`}
          sub={
            p.consumed_30d === 0 && p.calls_30d > 0
              ? `$${p.provider_cost_30d_usd.toFixed(2)} spent, nothing charged`
              : `$${p.provider_cost_30d_usd.toFixed(2)} provider cost`
          }
          tone={margin >= 0 ? "good" : "bad"}
        />
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Calls, all time"
          value={String(p.calls_total)}
          sub={`${p.calls_30d} in 30 days · ${p.minutes_30d}m`}
        />
        <Metric
          label="Failed, 30 days"
          value={String(p.failed_30d)}
          tone={p.failed_30d > 0 ? "bad" : "good"}
        />
        <Metric
          label="Granted"
          value={p.lifetime_granted.toFixed(0)}
          sub="Trial and manual credits"
        />
        <Metric
          label="Consumed"
          value={p.lifetime_consumed.toFixed(0)}
          sub={money(p.lifetime_consumed)}
        />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel
          title="Where the calls came from"
          description="A bill is usually queried because of one of these."
        >
          {!Object.keys(p.by_source).length ? (
            <Empty title="No calls yet" />
          ) : (
            <ul className="divide-y divide-slate-800/80">
              {Object.entries(p.by_source)
                .sort((a, b) => b[1] - a[1])
                .map(([source, count]) => (
                  <li
                    key={source}
                    className="flex items-center justify-between px-4 py-2.5 text-[0.8rem]"
                  >
                    <span className="text-slate-300">
                      {SOURCES[source] ?? source}
                    </span>
                    <span className="tabular-nums text-slate-100">{count}</span>
                  </li>
                ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Team"
          description="Everyone who can sign in to this account."
        >
          {!p.users.length ? (
            <Empty title="No users" />
          ) : (
            <Grid headers={["Name", "Email", "Role", "Last login"]}>
              {p.users.map((user) => (
                <tr key={user.id} className="text-slate-300">
                  <td className="py-2.5 pl-4 pr-3 text-slate-100">
                    {user.full_name}
                  </td>
                  <td className="px-3 text-[0.75rem] text-slate-400">
                    {user.email}
                  </td>
                  <td className="px-3">
                    <div className="flex gap-1">
                      <Pill value={user.role} />
                      {!user.is_active && <Pill value="inactive" />}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-3 text-[0.7rem] text-slate-500">
                    {when(user.last_login_at)}
                  </td>
                </tr>
              ))}
            </Grid>
          )}
        </Panel>
      </div>

      <div className="mt-5">
        <Panel
          title="Agents"
          description="What they built, and what each one has cost."
        >
          {!p.agents.length ? (
            <Empty
              title="No agents yet"
              hint="This account cannot place AI calls until it has one."
            />
          ) : (
            <Grid
              headers={[
                "Agent",
                "Language",
                "Calls",
                "Minutes",
                "Provider cost",
                "Status",
              ]}
            >
              {p.agents.map((agent) => (
                <tr key={agent.id} className="text-slate-300">
                  <td className="py-2.5 pl-4 pr-3">
                    <p className="text-slate-100">{agent.name}</p>
                    {agent.role_title && (
                      <p className="text-[0.65rem] text-slate-500">
                        {agent.role_title}
                      </p>
                    )}
                  </td>
                  <td className="px-3 text-[0.75rem] text-slate-400">
                    {agent.language}
                  </td>
                  <td className="px-3 tabular-nums">{agent.calls}</td>
                  <td className="px-3 tabular-nums">{agent.minutes}</td>
                  <td className="px-3 tabular-nums text-slate-400">
                    ${agent.provider_cost_usd.toFixed(2)}
                  </td>
                  <td className="px-3">
                    <Pill value={agent.is_active ? "active" : "inactive"} />
                  </td>
                </tr>
              ))}
            </Grid>
          )}
        </Panel>
      </div>

      <div className="mt-5">
        <Panel
          title="Recent calls"
          description={
            p.recent_calls.some((c) => c.source_detail?.startsWith(BACKFILLED))
              ? "The last 25, newest first. Some origins were inferred when attribution was added, not recorded at the time."
              : "The last 25, newest first."
          }
        >
          {!p.recent_calls.length ? (
            <Empty title="No calls yet" />
          ) : (
            <Grid
              headers={[
                "Number",
                "Status",
                "Origin",
                "Mode",
                "Duration",
                "Cost",
                "When",
              ]}
            >
              {p.recent_calls.map((call) => (
                <tr key={call.id} className="text-slate-300">
                  <td className="py-2.5 pl-4 pr-3 font-mono text-[0.75rem]">
                    {call.to_number}
                  </td>
                  <td className="px-3">
                    <Pill value={call.status} />
                  </td>
                  <td className="px-3 text-[0.75rem]">
                    {SOURCES[call.source] ?? call.source}
                    {call.source_detail &&
                      !call.source_detail.startsWith(BACKFILLED) && (
                        <span className="block text-[0.65rem] text-slate-500">
                          {call.source_detail}
                        </span>
                      )}
                  </td>
                  <td className="px-3 text-[0.75rem] text-slate-400">
                    {call.mode}
                  </td>
                  <td className="px-3 tabular-nums">
                    {call.duration_seconds ? `${call.duration_seconds}s` : "—"}
                  </td>
                  <td className="px-3 tabular-nums text-slate-400">
                    {call.cost_usd !== null
                      ? `$${call.cost_usd.toFixed(4)}`
                      : "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 text-[0.7rem] text-slate-500">
                    {when(call.created_at)}
                  </td>
                </tr>
              ))}
            </Grid>
          )}
        </Panel>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel
          title="Credit movements"
          description="The last 25 ledger entries."
        >
          {!p.recent_credits.length ? (
            <Empty title="Nothing yet" />
          ) : (
            <Grid headers={["Type", "Change", "After", "Note", "When"]}>
              {p.recent_credits.map((entry) => (
                <tr key={entry.id} className="text-slate-300">
                  <td className="py-2.5 pl-4 pr-3">
                    <Pill value={entry.kind} />
                  </td>
                  <td
                    className={`px-3 tabular-nums ${
                      entry.amount >= 0 ? "text-emerald-400" : "text-slate-300"
                    }`}
                  >
                    {entry.amount >= 0 ? "+" : ""}
                    {entry.amount.toFixed(2)}
                  </td>
                  <td className="px-3 tabular-nums text-slate-400">
                    {entry.balance_after.toFixed(0)}
                  </td>
                  <td className="max-w-[12rem] truncate px-3 text-[0.7rem] text-slate-500">
                    {entry.note ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 text-[0.7rem] text-slate-500">
                    {when(entry.created_at)}
                  </td>
                </tr>
              ))}
            </Grid>
          )}
        </Panel>

        <Panel title="Payments" description="The last 25 orders.">
          {!p.recent_orders.length ? (
            <Empty
              title="Never bought credits"
              hint="Running on trial or granted credits."
            />
          ) : (
            <Grid
              headers={["Reference", "Package", "Amount", "Status", "When"]}
            >
              {p.recent_orders.map((order) => (
                <tr key={order.id} className="text-slate-300">
                  <td className="py-2.5 pl-4 pr-3 font-mono text-[0.7rem] text-slate-400">
                    {order.reference}
                  </td>
                  <td className="px-3">{order.package_name}</td>
                  <td className="whitespace-nowrap px-3 tabular-nums">
                    {dollars(order.total_minor)}
                  </td>
                  <td className="px-3">
                    <div className="flex gap-1">
                      <Pill value={order.status} />
                      {order.status === "paid" &&
                        !order.credits_allocated_at && (
                          <Pill value="unallocated" />
                        )}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-3 text-[0.7rem] text-slate-500">
                    {when(order.paid_at ?? order.created_at)}
                  </td>
                </tr>
              ))}
            </Grid>
          )}
        </Panel>
      </div>
    </div>
  );
}
