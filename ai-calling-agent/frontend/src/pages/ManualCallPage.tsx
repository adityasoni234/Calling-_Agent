import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Field } from '@/components/ui/Field'
import { EmptyState, Table } from '@/components/ui/Table'
import { useBridgeCall, useCalls, useLeadLists, useLeads } from '@/hooks/api'
import { ApiError, NetworkError } from '@/lib/api'
import { formatDateTime, formatDuration } from '@/lib/format'
import type { Call, Lead } from '@/types/api'

const STORAGE_KEY = 'operator_number'

function storedNumber(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

/**
 * Call leads yourself, on the same rails as the agent.
 *
 * The platform rings the operator's phone first and bridges them to the lead
 * once they answer, so no softphone or headset is needed -- and the call still
 * lands in the same records, recordings and cost reporting as an AI call.
 */
export function ManualCallPage() {
  const [myNumber, setMyNumber] = useState(storedNumber)
  const [search, setSearch] = useState('')
  const [sheet, setSheet] = useState('')
  const [manual, setManual] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [placed, setPlaced] = useState<Call | null>(null)

  const { data: sheets } = useLeadLists()
  const { data: leads, isLoading } = useLeads({
    page: 1,
    search: search || undefined,
    list_id: sheet || undefined,
  })
  const { data: history } = useCalls({ page: 1, mode: 'human' })
  const bridge = useBridgeCall()

  const ready = myNumber.trim().length >= 6

  const call = async (body: { lead_id?: string; to_number?: string }) => {
    setError(null)
    setPlaced(null)
    try {
      localStorage.setItem(STORAGE_KEY, myNumber.trim())
    } catch {
      // A browser that blocks storage must not block the call.
    }
    try {
      setPlaced(await bridge.mutateAsync({ operator_number: myNumber.trim(), ...body }))
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof NetworkError
          ? err.message
          : 'Could not start the call',
      )
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Manual Calling"
        description="Call leads yourself. We ring your phone first, then connect you — so no softphone or headset is needed."
      />

      {error && <Alert tone="error">{error}</Alert>}
      {placed && (
        <Alert tone="success">
          Calling <span className="font-medium tabular-nums">{myNumber}</span> now — answer it and
          you will be connected to{' '}
          <span className="font-medium tabular-nums">{placed.to_number}</span>.{' '}
          <Link to={`/calls/${placed.id}`} className="font-medium underline">
            Open the call
          </Link>
        </Alert>
      )}

      <Card
        title="Your phone"
        description="The number we ring when you start a call. Remembered on this device."
      >
        <div className="flex flex-wrap items-end gap-3">
          <Field
            label="Ring me on"
            className="min-w-64 flex-1"
            value={myNumber}
            onChange={(event) => setMyNumber(event.target.value)}
            placeholder="+919812345678"
            hint="Include the country code. Your phone rings first, so the lead's phone only rings once you are actually on the line."
          />
          <div className="pb-[1.35rem]">
            <Badge value={ready ? 'ready' : 'pending'} />
          </div>
        </div>
      </Card>

      <Card title="Dial a number" description="Anyone, whether or not they are in your leads.">
        <div className="flex flex-wrap items-end gap-3">
          <Field
            label="Number to call"
            className="min-w-64 flex-1"
            value={manual}
            onChange={(event) => setManual(event.target.value)}
            placeholder="+919799918691"
          />
          <div className="pb-[1.35rem]">
            <Button
              onClick={() => call({ to_number: manual.trim() })}
              loading={bridge.isPending}
              disabled={!ready || manual.trim().length < 6}
            >
              Call
            </Button>
          </div>
        </div>
        {!ready && (
          <p className="mt-1 text-xs text-amber-700">Enter your own number above first.</p>
        )}
      </Card>

      <Card
        title="Call a lead"
        description="Everything the agent would know about them is on their record afterwards."
        flush
      >
        <div className="space-y-2 px-5 pt-4">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name, phone, company"
            className="w-full rounded-xl border-0 bg-white px-3 py-2 text-sm shadow-card ring-1 ring-inset ring-ink-200 focus:ring-2 focus:ring-brand-500"
          />
          {(sheets ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1">
              <SheetChip label="All leads" selected={!sheet} onClick={() => setSheet('')} />
              {(sheets ?? []).map((item) => (
                <SheetChip
                  key={item.id}
                  label={`${item.name} (${item.lead_count})`}
                  selected={sheet === item.id}
                  onClick={() => setSheet(item.id)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="px-5 pb-4">
          {isLoading ? (
            <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
          ) : !leads?.items.length ? (
            <EmptyState title="No leads match" hint="Try a different search or sheet." />
          ) : (
            <Table headers={['Lead', 'Phone', 'Status', 'Calls', 'Last called', '']}>
              {leads.items.map((lead: Lead) => (
                <tr key={lead.id} className="hover:bg-ink-50">
                  <td className="py-2.5 pl-5 pr-3 font-medium text-ink-900">{lead.name}</td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">{lead.phone_number}</td>
                  <td className="px-3 py-2.5">
                    <Badge value={lead.status} />
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">{lead.call_count}</td>
                  <td className="px-3 py-2.5 text-xs text-ink-500">
                    {formatDateTime(lead.last_called_at)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!ready || lead.status === 'do_not_call'}
                      onClick={() => call({ lead_id: lead.id })}
                    >
                      {lead.status === 'do_not_call' ? 'Do not call' : 'Call'}
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Card>

      <Card title="Your recent calls" description="Calls you placed yourself, not the agent's." flush>
        <div className="px-5 pb-4 pt-4">
          {!history?.items.length ? (
            <EmptyState
              title="No manual calls yet"
              hint="Calls you place from this page appear here with their recording and cost."
            />
          ) : (
            <Table headers={['To', 'Status', 'Duration', 'Cost', 'When', '']}>
              {history.items.map((row) => (
                <tr key={row.id} className="hover:bg-ink-50">
                  <td className="py-2.5 pl-5 pr-3 tabular-nums text-ink-800">{row.to_number}</td>
                  <td className="px-3 py-2.5">
                    <Badge value={row.status} />
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">
                    {formatDuration(row.duration_seconds)}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">
                    {row.cost_incomplete ? '—' : `$${row.cost_usd.toFixed(3)}`}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-ink-500">
                    {formatDateTime(row.started_at)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Link
                      to={`/calls/${row.id}`}
                      className="rounded-xl px-2.5 py-1.5 text-xs font-medium text-brand-600 hover:bg-brand-50"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Card>
    </div>
  )
}

function SheetChip({
  label,
  selected,
  onClick,
}: {
  label: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`max-w-48 truncate rounded-lg px-2.5 py-1 text-2xs font-medium transition-colors ${
        selected
          ? 'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200'
          : 'text-ink-500 hover:bg-ink-100 hover:text-ink-800'
      }`}
    >
      {label}
    </button>
  )
}
