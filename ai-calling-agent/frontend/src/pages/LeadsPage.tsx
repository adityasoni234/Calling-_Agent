import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { SheetTabs } from '@/components/SheetTabs'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Field } from '@/components/ui/Field'
import { Select, TextArea } from '@/components/ui/Inputs'
import { Modal } from '@/components/ui/Modal'
import { EmptyState, Pager, Table } from '@/components/ui/Table'
import {
  useAgents,
  useBridgeCall,
  useCreateLead,
  useDeleteLead,
  useImportLeads,
  useLeadLists,
  useLeads,
  usePlaceCall,
} from '@/hooks/api'
import { ApiError, NetworkError } from '@/lib/api'
import { downloadCsv, leadTemplateCsv } from '@/lib/csv'
import { formatDateTime } from '@/lib/format'
import { useAuthStore } from '@/stores/auth'
import type { ImportResult, Lead } from '@/types/api'

const STATUSES = [
  'new', 'contacted', 'interested', 'qualified', 'callback',
  'not_interested', 'unreachable', 'do_not_call', 'converted',
]

export function LeadsPage() {
  const [params] = useSearchParams()
  const [page, setPage] = useState(1)
  // Links from a call arrive with ?search=<phone>, so land on that lead.
  const [search, setSearch] = useState(params.get('search') ?? '')
  const [status, setStatus] = useState('')
  const [creating, setCreating] = useState(false)
  const [callFor, setCallFor] = useState<Lead | null>(null)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  // null means the "All leads" tab.
  const [sheet, setSheet] = useState<string | null>(null)

  const { data: sheets } = useLeadLists()
  const { data, isLoading } = useLeads({
    page,
    search: search || undefined,
    status: status || undefined,
    list_id: sheet ?? undefined,
  })
  const remove = useDeleteLead()
  const token = useAuthStore((state) => state.tokens?.access_token ?? null)
  const importLeads = useImportLeads(token)
  const fileInput = useRef<HTMLInputElement>(null)

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">Leads</h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-500">
            The people your agents call, and what came of it. Each uploaded sheet gets its own tab.
          </p>
        </div>
        <div className="flex gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={async (event) => {
              const file = event.target.files?.[0]
              if (!file) return
              try {
                const outcome = await importLeads.mutateAsync(file)
                setImportResult(outcome)
                // Land on the sheet that was just created rather than making
                // the user hunt for it among the tabs.
                if (outcome.lead_list) {
                  setSheet(outcome.lead_list.id)
                  setPage(1)
                }
              } catch (error) {
                setImportResult({
                  lead_list: null,
                  imported: 0,
                  skipped: 0,
                  errors: [error instanceof Error ? error.message : 'Import failed'],
                })
              }
              event.target.value = ''
            }}
          />
          <Button
            variant="ghost"
            onClick={() => downloadCsv('leads-template.csv', leadTemplateCsv())}
            title="A CSV with the right columns and two example rows"
          >
            Template
          </Button>
          <Button
            variant="secondary"
            loading={importLeads.isPending}
            onClick={() => fileInput.current?.click()}
          >
            Import CSV
          </Button>
          <Button onClick={() => setCreating(true)}>New lead</Button>
        </div>
      </header>

      {importResult && (
        <Alert tone={importResult.imported ? 'success' : 'warning'}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <span className="font-medium">
                Imported {importResult.imported} lead{importResult.imported === 1 ? '' : 's'}
                {importResult.skipped > 0 && `, skipped ${importResult.skipped}`}.
              </span>
              {importResult.skipped > 0 && (
                <span className="mt-0.5 block text-xs">
                  Rows are skipped when the phone number is missing, too short, or already
                  in your list.
                </span>
              )}
              {importResult.errors.length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-xs">
                  {importResult.errors.slice(0, 5).map((error) => (
                    <li key={error}>{error}</li>
                  ))}
                </ul>
              )}
            </div>
            <button type="button" onClick={() => setImportResult(null)} className="text-xs underline">
              dismiss
            </button>
          </div>
        </Alert>
      )}

      <Card flush>
        <SheetTabs
          sheets={sheets ?? []}
          active={sheet}
          total={sheets ? undefined : data?.total}
          onSelect={(id) => {
            setSheet(id)
            setPage(1)
          }}
        />
        <div className="mb-4 flex flex-wrap gap-3 px-5 pt-4">
          <input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
            placeholder="Search name, phone, email, company"
            className="min-w-56 flex-1 rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-inset ring-ink-200 focus:ring-2 focus:ring-brand-500"
          />
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
              <option key={value} value={value}>
                {value.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </div>

        <div className="px-5 pb-4">
        {isLoading ? (
          <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
        ) : !data?.items.length ? (
          <EmptyState
            title={
              search || status
                ? 'No leads match that filter'
                : sheet
                  ? 'This sheet is empty'
                  : 'No leads yet'
            }
            hint={
              search || status
                ? 'Try a different search, or clear the status filter.'
                : sheet
                  ? 'Every lead that was on this sheet has since been deleted.'
                  : 'Import a CSV exported from your CRM — name and phone are the only required columns — or add one by hand to try a call.'
            }
            action={
              search || status || sheet ? undefined : (
                <>
                  <Button onClick={() => fileInput.current?.click()}>Import a CSV</Button>
                  <Button variant="secondary" onClick={() => setCreating(true)}>
                    Add one by hand
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => downloadCsv('leads-template.csv', leadTemplateCsv())}
                  >
                    Download template
                  </Button>
                </>
              )
            }
          />
        ) : (
          <>
            <Table headers={['Name', 'Phone', 'Company', 'Status', 'Interest', 'Score', 'Calls', 'Last called', '']}>
              {data.items.map((lead) => (
                <tr key={lead.id} className="hover:bg-ink-50">
                  <td className="px-3 py-2.5 font-medium text-ink-900">{lead.name}</td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">{lead.phone_number}</td>
                  <td className="px-3 py-2.5 text-ink-600">{lead.company_name ?? '—'}</td>
                  <td className="px-3 py-2.5"><Badge value={lead.status} /></td>
                  <td className="px-3 py-2.5"><Badge value={lead.interest_level} /></td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-700">{lead.lead_score}</td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-600">{lead.call_count}</td>
                  <td className="px-3 py-2.5 text-xs text-ink-500">{formatDateTime(lead.last_called_at)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" variant="secondary" onClick={() => setCallFor(lead)}>
                        Call
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (confirm(`Delete ${lead.name}?`)) remove.mutate(lead.id)
                        }}
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </Table>
            <Pager page={data.page} pages={data.pages} total={data.total} onChange={setPage} />
          </>
        )}
        </div>
      </Card>

      {creating && <LeadEditor onClose={() => setCreating(false)} />}
      {callFor && <CallDialog lead={callFor} onClose={() => setCallFor(null)} />}
    </div>
  )
}

function LeadEditor({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({
    name: '',
    phone_number: '',
    email: '',
    company_name: '',
    notes: '',
  })
  const [error, setError] = useState<string | null>(null)
  const create = useCreateLead()

  const submit = async () => {
    setError(null)
    try {
      await create.mutateAsync({
        name: form.name,
        phone_number: form.phone_number,
        email: form.email || null,
        company_name: form.company_name || null,
        notes: form.notes || null,
      })
      onClose()
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not create the lead')
    }
  }

  return (
    <Modal open title="New lead" onClose={onClose}>
      <div className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <Field label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Field
          label="Phone number"
          value={form.phone_number}
          onChange={(e) => setForm({ ...form, phone_number: e.target.value })}
          hint="Ten digits are assumed to be Indian; anything else needs a country code."
        />
        <Field label="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <Field label="Company" value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
        <TextArea label="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={submit} loading={create.isPending}>Create lead</Button>
      </footer>
    </Modal>
  )
}

export function CallDialog({ lead, onClose }: { lead: Lead; onClose: () => void }) {
  const { data: agents } = useAgents()
  const active = agents?.items.filter((agent) => agent.is_active) ?? []
  // With one agent, asking which to use is a dialog that answers itself.
  const [agentId, setAgentId] = useState('')
  const resolved = agentId || (active.length === 1 ? active[0].id : '')
  const [error, setError] = useState<string | null>(null)
  const [by, setBy] = useState<'agent' | 'me'>('agent')
  // Remembered so you are not retyping your own number on every call.
  const [myNumber, setMyNumber] = useState(() => {
    try {
      return localStorage.getItem('operator_number') ?? ''
    } catch {
      return ''
    }
  })
  const place = usePlaceCall()
  const bridge = useBridgeCall()

  const submit = async () => {
    setError(null)
    try {
      if (by === 'me') {
        try {
          localStorage.setItem('operator_number', myNumber.trim())
        } catch {
          // A browser that blocks storage should not block the call.
        }
        await bridge.mutateAsync({ operator_number: myNumber.trim(), lead_id: lead.id })
      } else {
        await place.mutateAsync({ agent_id: resolved, lead_id: lead.id })
      }
      onClose()
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not place the call')
    }
  }

  return (
    <Modal open title={`Call ${lead.name}`} onClose={onClose}>
      <div className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <p className="text-sm text-ink-600">
          Dialing <span className="font-medium tabular-nums">{lead.phone_number}</span>
        </p>

        <div className="flex gap-2">
          {(
            [
              ['agent', 'AI agent calls'],
              ['me', 'I call them'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setBy(value)}
              className={`flex-1 rounded-xl px-3 py-2 text-xs font-medium transition-colors ${
                by === value
                  ? 'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200'
                  : 'bg-white text-ink-500 ring-1 ring-inset ring-ink-200 hover:bg-ink-50'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {by === 'me' ? (
          <Field
            label="Ring me on"
            value={myNumber}
            onChange={(event) => setMyNumber(event.target.value)}
            placeholder="+919812345678"
            hint="Your phone rings first. Answer it and you are connected to the lead — so their phone only rings once you are on the line."
          />
        ) : null}
        {by === 'me' ? null : active.length === 0 ? (
          <Alert tone="warning">
            No active agent yet. Create one first — it decides what gets said on the call.
          </Alert>
        ) : active.length === 1 ? (
          <p className="text-sm text-ink-600">
            Using <span className="font-medium text-ink-900">{active[0].name}</span>,{' '}
            {active[0].role_title}.
          </p>
        ) : (
          <Select label="Agent" value={resolved} onChange={(event) => setAgentId(event.target.value)}>
            <option value="">Choose an agent…</option>
            {active.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} — {agent.role_title}
              </option>
            ))}
          </Select>
        )}
      </div>
      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button
          onClick={submit}
          loading={place.isPending || bridge.isPending}
          disabled={by === 'me' ? myNumber.trim().length < 6 : !resolved}
        >
          {by === 'me' ? 'Ring my phone' : 'Place call'}
        </Button>
      </footer>
    </Modal>
  )
}
