import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card } from '@/components/ui/Card'
import { EmptyState, Pager, Table } from '@/components/ui/Table'
import { RecordingPlayer } from '@/components/RecordingPlayer'
import { useCall, useCalls, useReprocessCall } from '@/hooks/api'
import { formatCurrency, formatDateTime, formatDuration } from '@/lib/format'

const STATUSES = [
  'initiated', 'ringing', 'in_progress', 'completed',
  'failed', 'no_answer', 'busy', 'canceled',
]

export function CallsPage() {
  const [params] = useSearchParams()
  const campaignId = params.get('campaign') ?? undefined
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')

  const { data, isLoading } = useCalls({ page, status: status || undefined, campaign_id: campaignId })

  return (
    <div className="space-y-5">
      <PageHeader
        title="Call History"
        description="Every call with its transcript, recording, outcome and cost."
      />

      <Card>
        <div className="mb-4">
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value)
              setPage(1)
            }}
            className="rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-inset ring-ink-200 focus:ring-2 focus:ring-brand-500"
          >
            <option value="">All statuses</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>

        {isLoading ? (
          <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
        ) : !data?.items.length ? (
          <EmptyState
            title={status ? 'No calls with that status' : 'No calls yet'}
            hint={
              status
                ? 'Clear the filter to see everything.'
                : 'Call a single lead yourself to try it, or start a campaign to dial a whole list.'
            }
            action={
              status ? (
                <Button variant="secondary" onClick={() => setStatus('')}>
                  Clear filter
                </Button>
              ) : (
                <>
                  <Link
                    to="/manual"
                    className="rounded-xl bg-brand-sheen px-2.5 py-1.5 text-xs font-medium text-white shadow-glow transition-all hover:brightness-110"
                  >
                    Call someone now
                  </Link>
                  <Link
                    to="/campaigns"
                    className="rounded-xl bg-white px-2.5 py-1.5 text-xs font-medium text-ink-700 shadow-card ring-1 ring-inset ring-ink-200 transition-colors hover:bg-ink-50"
                  >
                    Start a campaign
                  </Link>
                </>
              )
            }
          />
        ) : (
          <>
            <Table headers={['Started', 'To', 'Status', 'Duration', 'Cost', 'Summary', '']}>
              {data.items.map((call) => (
                <tr key={call.id} className="hover:bg-ink-50">
                  <td className="whitespace-nowrap px-3 py-2.5 text-xs text-ink-500">
                    {formatDateTime(call.started_at ?? call.created_at)}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-700">{call.to_number}</td>
                  <td className="px-3 py-2.5"><Badge value={call.status} /></td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">
                    {call.duration_seconds ? formatDuration(call.duration_seconds) : '—'}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-700">
                    {formatCurrency(call.cost_usd)}
                    {call.cost_incomplete && (
                      <span title="Some usage had no verified rate" className="ml-1 text-amber-500">*</span>
                    )}
                  </td>
                  <td className="max-w-xs truncate px-3 py-2.5 text-ink-600">
                    {call.summary ?? <span className="text-ink-400">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Link
                      to={`/calls/${call.id}`}
                      className="text-sm font-medium text-brand-600 hover:text-brand-700"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </Table>
            <Pager page={data.page} pages={data.pages} total={data.total} onChange={setPage} />
          </>
        )}
      </Card>
    </div>
  )
}

export function CallDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: call, isLoading } = useCall(id)
  const reprocess = useReprocessCall(id ?? '')

  if (isLoading || !call) {
    return <p className="py-10 text-center text-sm text-ink-500">Loading…</p>
  }

  const extracted = call.extracted_data ?? {}

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/calls" className="text-xs text-ink-500 hover:text-ink-700">← All calls</Link>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-semibold text-ink-900">
            <span className="tabular-nums">{call.to_number}</span>
            <Badge value={call.status} />
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-500">
            <span>{formatDateTime(call.started_at ?? call.created_at)}</span>
            <span aria-hidden>·</span>
            <span>{formatDuration(call.duration_seconds)}</span>
            <span aria-hidden>·</span>
            <span>via {call.provider}</span>
            {call.end_reason && (
              <>
                <span aria-hidden>·</span>
                <span>ended: {call.end_reason.replace(/_/g, ' ')}</span>
              </>
            )}
            {call.lead_id && (
              <>
                <span aria-hidden>·</span>
                <Link
                  to={`/leads?search=${encodeURIComponent(call.to_number)}`}
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  View lead
                </Link>
              </>
            )}
            {call.campaign_id && (
              <>
                <span aria-hidden>·</span>
                <Link
                  to={`/campaigns/${call.campaign_id}`}
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  View campaign
                </Link>
              </>
            )}
          </p>
        </div>
        <Button variant="secondary" onClick={() => reprocess.mutate()} loading={reprocess.isPending}>
          Re-run analysis
        </Button>
      </header>

      {call.error && <Alert tone="error">{call.error}</Alert>}
      {call.cost_incomplete && (
        <Alert tone="warning">
          This cost is a floor, not a total: at least one usage line had no verified rate. Add the
          missing rates in Settings → Pricing to complete it.
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Transcript" description={`${call.turns.length} turns`}>
            {!call.turns.length ? (
              <EmptyState title="No transcript" hint="The call never reached a conversation." />
            ) : (
              <ol className="space-y-3">
                {call.turns.map((turn) => (
                  <li
                    key={turn.turn_index}
                    className={`flex ${turn.role === 'agent' ? 'justify-start' : 'justify-end'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-xl px-3.5 py-2 text-sm ${
                        turn.role === 'agent'
                          ? 'bg-ink-100 text-ink-800'
                          : 'bg-brand-600 text-white'
                      }`}
                    >
                      <p className="whitespace-pre-wrap">{turn.content}</p>
                      <p
                        className={`mt-1 text-[11px] ${
                          turn.role === 'agent' ? 'text-ink-500' : 'text-brand-100'
                        }`}
                      >
                        {turn.role}
                        {turn.state && ` · ${turn.state.replace(/_/g, ' ')}`}
                        {turn.latency_ms !== null && ` · ${turn.latency_ms}ms`}
                        {turn.barge_in && ' · interrupted'}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          {call.summary && (
            <Card title="Summary">
              <p className="text-sm leading-relaxed text-ink-700">{call.summary}</p>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card title="Cost breakdown" description={formatCurrency(call.cost_usd)}>
            {!call.usage.length ? (
              <p className="text-sm text-ink-500">No usage recorded.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {call.usage.map((line, index) => (
                  <li key={index} className="flex items-baseline justify-between gap-3">
                    <span className="text-ink-600">
                      {line.component}
                      <span className="ml-1 text-xs text-ink-400">
                        {line.provider} · {line.quantity.toFixed(2)} {line.unit}
                      </span>
                    </span>
                    <span className="whitespace-nowrap tabular-nums font-medium text-ink-900">
                      {line.priced ? (
                        formatCurrency(line.cost_usd ?? 0)
                      ) : (
                        <span className="text-amber-600" title="No verified rate for this line">
                          unpriced
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {Object.keys(extracted).length > 0 && (
            <Card title="Extracted data">
              <dl className="space-y-2 text-sm">
                {Object.entries(extracted)
                  .filter(([, value]) => value !== null && value !== '' && !(Array.isArray(value) && !value.length))
                  .map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-4 border-b border-ink-100 pb-1.5">
                      <dt className="text-ink-500">{key.replace(/_/g, ' ')}</dt>
                      <dd className="text-right font-medium text-ink-900">
                        {Array.isArray(value) ? value.join(', ') : String(value)}
                      </dd>
                    </div>
                  ))}
              </dl>
            </Card>
          )}

          {call.recording_url && (
            <Card title="Recording" description="Streamed through the API — carrier links need credentials">
              <RecordingPlayer callId={call.id} />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
