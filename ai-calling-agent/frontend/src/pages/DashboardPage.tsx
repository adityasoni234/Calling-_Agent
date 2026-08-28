import { Alert } from '@/components/ui/Alert'
import { Card } from '@/components/ui/Card'
import { StatCard } from '@/components/ui/StatCard'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { useHealth } from '@/hooks/useHealth'
import { formatDateTime } from '@/lib/format'

/**
 * Metric tiles are rendered with real placeholders, not invented numbers. They
 * start reporting once calls exist (Phase 3) and cost tracking lands (Phase 9).
 */
const METRICS = [
  { label: 'Total calls', hint: 'From Phase 3' },
  { label: 'Calls today', hint: 'From Phase 3' },
  { label: 'Active campaigns', hint: 'From Phase 7' },
  { label: 'Total leads', hint: 'From Phase 7' },
  { label: 'Qualified leads', hint: 'From Phase 8' },
  { label: 'Avg. duration', hint: 'From Phase 3' },
  { label: 'Total cost', hint: 'From Phase 9' },
  { label: 'Cost per call', hint: 'From Phase 9' },
]

export function DashboardPage() {
  const { data: user, isLoading } = useCurrentUser()
  const { data: health } = useHealth()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">
          {user ? `Welcome back, ${user.full_name.split(' ')[0]}` : 'Overview'}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {user?.organization.name ?? 'Loading your workspace…'}
        </p>
      </div>

      {health && health.database !== 'ok' && (
        <Alert tone="warning">
          The API is running but cannot reach PostgreSQL. Check the <code>postgres</code> service.
        </Alert>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {METRICS.map((metric) => (
          <StatCard key={metric.label} label={metric.label} value="—" hint={metric.hint} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Your account" description="Verified against the API on every load">
          <dl className="divide-y divide-slate-100 text-sm">
            {[
              { label: 'Name', value: user?.full_name },
              { label: 'Email', value: user?.email },
              // Only the role is a lowercase enum worth title-casing; capitalising
              // an email address mangles it.
              { label: 'Role', value: user?.role, capitalize: true },
              { label: 'Organization', value: user?.organization.name },
              { label: 'Timezone', value: user?.organization.timezone },
              { label: 'Last sign-in', value: formatDateTime(user?.last_login_at) },
            ].map(({ label, value, capitalize }) => (
              <div key={label} className="flex justify-between gap-4 py-2.5">
                <dt className="text-slate-500">{label}</dt>
                <dd
                  className={`truncate font-medium text-slate-900 ${capitalize ? 'capitalize' : ''}`}
                >
                  {isLoading ? '…' : (value ?? '—')}
                </dd>
              </div>
            ))}
          </dl>
        </Card>

        <Card title="What's next" description="Roadmap for this platform">
          <ol className="space-y-2.5 text-sm">
            {[
              ['Phase 1', 'Auth, database, dashboard shell', true],
              ['Phase 2', 'Agent configuration and provider abstraction', false],
              ['Phase 3', 'Telephony integration and call lifecycle', false],
              ['Phase 4', 'Realtime STT → LLM → TTS pipeline', false],
              ['Phase 5', 'Barge-in, silence handling, conversation state', false],
              ['Phase 6', 'Knowledge base and RAG over pgvector', false],
              ['Phase 7', 'Leads, campaigns, controlled concurrency', false],
              ['Phase 8', 'Summaries, extraction, lead scoring', false],
              ['Phase 9', 'Analytics and cost tracking', false],
            ].map(([phase, label, done]) => (
              <li key={phase as string} className="flex items-start gap-3">
                <span
                  className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-bold ${
                    done ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'
                  }`}
                >
                  {done ? '✓' : ''}
                </span>
                <span>
                  <span className="font-medium text-slate-900">{phase}</span>
                  <span className="text-slate-500"> — {label}</span>
                </span>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </div>
  )
}
