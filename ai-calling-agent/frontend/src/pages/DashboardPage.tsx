import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { EmptyState, Table } from "@/components/ui/Table";
import { SetupChecklist } from "@/components/SetupChecklist";
import { StatCard } from "@/components/ui/StatCard";
import { useAnalytics, usePlatformSettings } from "@/hooks/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { formatCurrency, formatDuration } from "@/lib/format";

const OUTCOME_COLORS: Record<string, string> = {
  completed: "#059669",
  in_progress: "#3364fb",
  ringing: "#8eb4ff",
  initiated: "#94a3b8",
  failed: "#dc2626",
  no_answer: "#f59e0b",
  busy: "#fbbf24",
  canceled: "#cbd5e1",
};

export function DashboardPage() {
  const { data: user } = useCurrentUser();
  const { data: analytics, isLoading } = useAnalytics();
  const { data: settings } = usePlatformSettings();

  const overview = analytics?.overview;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-ink-900">
          {user ? `Welcome back, ${user.full_name.split(" ")[0]}` : "Overview"}
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          {user?.organization.name ?? "Loading…"}
        </p>
      </header>

      {settings?.using_mocks && (
        <Alert tone="warning">
          Mock providers are active — the pipeline runs end to end, but no real
          calls are placed. Add provider keys in{" "}
          <Link to="/settings" className="underline">
            Settings
          </Link>{" "}
          to go live.
        </Alert>
      )}
      {overview && overview.calls_with_incomplete_cost > 0 && (
        <Alert tone="info">
          {overview.calls_with_incomplete_cost} call
          {overview.calls_with_incomplete_cost === 1 ? " has" : "s have"} usage
          with no verified rate, so the totals below are a floor. Add rates in{" "}
          <Link to="/settings" className="underline">
            Settings → Pricing
          </Link>
          .
        </Alert>
      )}

      <SetupChecklist />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total calls"
          value={String(overview?.total_calls ?? 0)}
          pending={isLoading}
        />
        <StatCard
          label="Calls today"
          value={String(overview?.calls_today ?? 0)}
          pending={isLoading}
        />
        <StatCard
          label="Active campaigns"
          value={String(overview?.active_campaigns ?? 0)}
          pending={isLoading}
        />
        <StatCard
          label="Total leads"
          value={String(overview?.total_leads ?? 0)}
          pending={isLoading}
        />
        <StatCard
          label="Qualified leads"
          value={String(overview?.qualified_leads ?? 0)}
          hint={`${overview?.interested_leads ?? 0} interested`}
          pending={isLoading}
        />
        <StatCard
          label="Avg. duration"
          value={formatDuration(overview?.average_duration_seconds ?? 0)}
          pending={isLoading}
        />
        <StatCard
          label="Total cost"
          value={formatCurrency(overview?.total_cost_usd ?? 0)}
          hint={`${formatCurrency(overview?.cost_today_usd ?? 0)} today`}
          pending={isLoading}
        />
        <StatCard
          label="Cost per call"
          value={formatCurrency(overview?.cost_per_call_usd ?? 0)}
          hint={`${formatCurrency(overview?.cost_per_minute_usd ?? 0)} / min`}
          pending={isLoading}
        />
      </div>

      <section className="relative animate-fade-up overflow-hidden rounded-2xl bg-brand-sheen p-6 shadow-glow sm:p-7">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-24 h-64 w-64 rounded-full bg-white/10 blur-3xl"
        />
        <div className="relative flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-xl">
            <p className="text-2xs font-semibold uppercase tracking-wider text-brand-100">
              Cost per qualified lead
            </p>
            <p className="mt-3 text-5xl font-semibold leading-none tabular-nums text-white">
              {formatCurrency(overview?.cost_per_qualified_lead_usd ?? 0)}
            </p>
            <p className="mt-4 text-sm leading-relaxed text-brand-100">
              The number that decides whether a campaign is worth running. A
              campaign with a higher cost per call and a better qualification
              rate is the cheaper campaign — compare this across campaigns
              below, not cost per call.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-white">
            {[
              ["Qualified", String(overview?.qualified_leads ?? 0)],
              ["Interested", String(overview?.interested_leads ?? 0)],
              ["Completed calls", String(overview?.completed_calls ?? 0)],
              ["Spend today", formatCurrency(overview?.cost_today_usd ?? 0)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-2xs uppercase tracking-wider text-brand-100/80">
                  {label}
                </dt>
                <dd className="mt-0.5 text-lg font-semibold tabular-nums">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Calls and spend" description="Last 14 days">
          {!analytics?.calls_per_day.length ? (
            <EmptyState title="No calls yet" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={analytics.calls_per_day}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                />
                <YAxis
                  yAxisId="left"
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="calls"
                  stroke="#1d43f0"
                  strokeWidth={2}
                  name="Calls"
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="cost_usd"
                  stroke="#059669"
                  strokeWidth={2}
                  name="Cost (USD)"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Call outcomes">
          {!analytics?.outcomes.length ? (
            <EmptyState title="No outcomes yet" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={analytics.outcomes}
                  dataKey="count"
                  nameKey="status"
                  innerRadius={55}
                  outerRadius={90}
                  paddingAngle={2}
                >
                  {analytics.outcomes.map((entry) => (
                    <Cell
                      key={entry.status}
                      fill={OUTCOME_COLORS[entry.status] ?? "#94a3b8"}
                    />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Lead funnel">
          {!analytics?.lead_funnel.length ? (
            <EmptyState title="No leads yet" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={analytics.lead_funnel}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="status"
                  tick={{ fontSize: 10 }}
                  stroke="#94a3b8"
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                  allowDecimals={false}
                />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                <Bar dataKey="count" fill="#3364fb" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Where the money goes" description="Spend by component">
          {!analytics?.cost_breakdown.length ? (
            <EmptyState title="No usage recorded yet" />
          ) : (
            <Table headers={["Component", "Quantity", "Cost", "Unpriced"]}>
              {analytics.cost_breakdown.map((line) => (
                <tr key={line.component}>
                  <td className="px-3 py-2 font-medium text-ink-900">
                    {line.component}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-ink-600">
                    {line.quantity.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-ink-900">
                    {formatCurrency(line.cost_usd)}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {line.unpriced_lines > 0 ? (
                      <span className="text-amber-600">
                        {line.unpriced_lines}
                      </span>
                    ) : (
                      <span className="text-ink-400">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <Card title="Campaign performance">
        {!analytics?.campaigns.length ? (
          <EmptyState
            title="No campaigns yet"
            hint="Create one to start comparing."
          />
        ) : (
          <Table
            headers={[
              "Campaign",
              "Status",
              "Calls",
              "Completed",
              "Cost",
              "Cost / call",
            ]}
          >
            {analytics.campaigns.map((campaign) => (
              <tr key={campaign.campaign_id} className="hover:bg-ink-50">
                <td className="px-3 py-2.5 font-medium text-ink-900">
                  <Link
                    to={`/campaigns/${campaign.campaign_id}`}
                    className="hover:text-brand-700"
                  >
                    {campaign.name}
                  </Link>
                </td>
                <td className="px-3 py-2.5 text-ink-600">{campaign.status}</td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {campaign.calls}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {campaign.completed}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-900">
                  {formatCurrency(campaign.cost_usd)}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-900">
                  {formatCurrency(campaign.cost_per_call_usd)}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
