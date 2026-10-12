import { Link } from "react-router-dom";

import { usePlatformOrganizations, usePlatformOverview } from "@/admin/hooks";
import { Empty, Grid, Metric, PageTitle, Panel, Pill } from "@/admin/ui";
import { money } from "@/admin/format";
import { formatDateTime } from "@/lib/format";

export function Overview() {
  const { data: overview, isLoading } = usePlatformOverview();
  const { data: organizations } = usePlatformOrganizations();

  const lowBalance = (organizations ?? [])
    .filter((org) => !org.is_suspended && org.credit_balance < 500)
    .sort((a, b) => a.credit_balance - b.credit_balance);

  const busiest = [...(organizations ?? [])]
    .sort((a, b) => b.calls_30d - a.calls_30d)
    .slice(0, 5);

  return (
    <div>
      <PageTitle
        title="Overview"
        description="Last 30 days across the whole platform."
      />

      {isLoading || !overview ? (
        <p className="py-16 text-center text-sm text-ink-400">Loading…</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric
              label="Customers"
              value={String(overview.organizations)}
              sub={`${overview.active_organizations} active · ${overview.suspended} suspended`}
            />
            <Metric
              label="Calls"
              value={String(overview.calls_30d)}
              sub={`${overview.minutes_30d} minutes`}
            />
            <Metric
              label="Billed"
              value={money(overview.credits_consumed_30d)}
              sub={`${overview.credits_consumed_30d.toFixed(0)} credits consumed`}
            />
            <Metric
              label="Gross margin"
              value={`$${overview.gross_margin_30d_usd.toFixed(2)}`}
              sub={`after $${overview.provider_cost_30d_usd.toFixed(2)} provider cost`}
              tone={overview.gross_margin_30d_usd >= 0 ? "good" : "bad"}
            />
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Metric
              label="Credits outstanding"
              value={overview.credits_outstanding.toFixed(0)}
              sub={`${money(overview.credits_outstanding)} of unused balance owed to customers`}
            />
            <Metric
              label="Users"
              value={String(overview.users)}
              sub="across every customer"
            />
          </div>

          {/* Messaging on its own row. A platform view that counts only
              calls under-reports every customer who mostly texts. */}
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Metric
              label="Messages · 30d"
              value={String(overview.messages_30d)}
              sub={`${overview.messages_delivered_30d} delivered`}
            />
            <Metric
              label="Message revenue · 30d"
              value={`$${overview.message_revenue_30d_usd.toFixed(2)}`}
              tone={overview.message_revenue_30d_usd > 0 ? "good" : "neutral"}
            />
            <Metric
              label="Delivery rate"
              value={
                overview.delivery_rate === null
                  ? "—"
                  : `${overview.delivery_rate}%`
              }
              sub="Of attempted sends, excluding opt-outs"
              tone={
                overview.delivery_rate !== null && overview.delivery_rate < 85
                  ? "bad"
                  : "good"
              }
            />
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <Panel
              title="Running low"
              description="Customers who will stop calling soon unless they top up."
            >
              {lowBalance.length === 0 ? (
                <Empty title="Everyone has credit" />
              ) : (
                <Grid headers={["Customer", "Balance", "Calls · 30d", ""]}>
                  {lowBalance.map((org) => (
                    <tr key={org.id}>
                      <td className="py-2.5 pl-4 pr-3 text-ink-800">
                        {org.name}
                      </td>
                      <td
                        className={`px-3 py-2.5 tabular-nums ${
                          org.credit_balance <= 0
                            ? "text-red-700"
                            : "text-amber-700"
                        }`}
                      >
                        {org.credit_balance.toFixed(0)}
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-ink-500">
                        {org.calls_30d}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <Link
                          to="/customers"
                          className="text-[0.7rem] text-ink-500 underline-offset-2 hover:text-ink-800 hover:underline"
                        >
                          Manage
                        </Link>
                      </td>
                    </tr>
                  ))}
                </Grid>
              )}
            </Panel>

            <Panel
              title="Busiest customers"
              description="By calls placed in the last 30 days."
            >
              {busiest.length === 0 ? (
                <Empty title="No calls yet" />
              ) : (
                <Grid
                  headers={[
                    "Customer",
                    "Plan",
                    "Calls",
                    "Our cost",
                    "Last call",
                  ]}
                >
                  {busiest.map((org) => (
                    <tr key={org.id}>
                      <td className="py-2.5 pl-4 pr-3 text-ink-800">
                        {org.name}
                      </td>
                      <td className="px-3 py-2.5">
                        <Pill value={org.plan} />
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-ink-700">
                        {org.calls_30d}
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-ink-500">
                        ${org.provider_cost_usd.toFixed(2)}
                      </td>
                      <td className="px-3 py-2.5 text-[0.7rem] text-ink-400">
                        {org.last_call_at
                          ? formatDateTime(org.last_call_at)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </Grid>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
