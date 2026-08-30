import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Field } from '@/components/ui/Field'
import { Select } from '@/components/ui/Inputs'
import { Modal } from '@/components/ui/Modal'
import { EmptyState, Pager, Table } from '@/components/ui/Table'
import { LeadPicker } from '@/components/LeadPicker'
import { StatCard } from '@/components/ui/StatCard'
import {
  useAgents,
  useCampaign,
  useCampaignControl,
  useCampaignLeads,
  useCampaigns,
  useCreateCampaign,
  useLead,
} from '@/hooks/api'
import { ApiError } from '@/lib/api'
import { formatCurrency, formatDateTime } from '@/lib/format'

export function CampaignsPage() {
  const { data, isLoading } = useCampaigns()
  const [creating, setCreating] = useState(false)

  return (
    <div className="space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Campaigns</h1>
          <p className="mt-1 text-sm text-ink-500">
            Batch outbound calling, with a hard cap on how many run at once.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>New campaign</Button>
      </header>

      <Card>
        {isLoading ? (
          <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
        ) : !data?.items.length ? (
          <EmptyState
            title="No campaigns yet"
            hint="A campaign dials a list of leads with an agent, inside calling hours you set, a few at a time. You need at least one agent and some leads first."
          />
        ) : (
          <Table headers={['Name', 'Status', 'Calling hours', 'Concurrency', 'Retries', '']}>
            {data.items.map((campaign) => (
              <tr key={campaign.id} className="hover:bg-ink-50">
                <td className="px-3 py-2.5 font-medium text-ink-900">
                  <Link to={`/campaigns/${campaign.id}`} className="hover:text-brand-700">
                    {campaign.name}
                  </Link>
                </td>
                <td className="px-3 py-2.5"><Badge value={campaign.status} /></td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {campaign.calling_hours_start.slice(0, 5)}–{campaign.calling_hours_end.slice(0, 5)}
                  <span className="ml-1 text-xs text-ink-400">{campaign.timezone}</span>
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">{campaign.max_concurrent_calls}</td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">{campaign.max_retries}</td>
                <td className="px-3 py-2.5 text-right">
                  <Link
                    to={`/campaigns/${campaign.id}`}
                    className="text-sm font-medium text-brand-600 hover:text-brand-700"
                  >
                    Open
                  </Link>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {creating && <CampaignEditor onClose={() => setCreating(false)} />}
    </div>
  )
}

export function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: campaign, isLoading } = useCampaign(id)
  const control = useCampaignControl(id ?? '')
  const [error, setError] = useState<string | null>(null)

  if (isLoading || !campaign) {
    return <p className="py-10 text-center text-sm text-ink-500">Loading…</p>
  }

  const act = async (action: 'start' | 'pause' | 'stop' | 'dispatch') => {
    setError(null)
    try {
      await control.mutateAsync(action)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed')
    }
  }

  const { stats } = campaign
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/campaigns" className="text-xs text-ink-500 hover:text-ink-700">
            ← All campaigns
          </Link>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-semibold text-ink-900">
            {campaign.name}
            <Badge value={campaign.status} />
          </h1>
        </div>
        <div className="flex gap-2">
          {campaign.status !== 'running' && campaign.status !== 'completed' && (
            <Button onClick={() => act('start')} loading={control.isPending}>Start</Button>
          )}
          {campaign.status === 'running' && (
            <>
              <Button variant="secondary" onClick={() => act('dispatch')}>Dial now</Button>
              <Button variant="secondary" onClick={() => act('pause')}>Pause</Button>
            </>
          )}
          {campaign.status !== 'stopped' && campaign.status !== 'completed' && (
            <Button variant="danger" onClick={() => act('stop')}>Stop</Button>
          )}
        </div>
      </header>

      {error && <Alert tone="error">{error}</Alert>}
      {campaign.status === 'running' && !stats.within_calling_hours && (
        <Alert tone="warning">
          Outside the configured calling window ({campaign.calling_hours_start.slice(0, 5)}–
          {campaign.calling_hours_end.slice(0, 5)} {campaign.timezone}), so no calls are being
          placed. This limit is enforced deliberately.
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Leads" value={String(stats.total_leads)} hint={`${stats.pending} pending`} />
        <StatCard label="Calls made" value={String(stats.calls_made)} hint={`${stats.active_calls} live now`} />
        <StatCard label="Completed" value={String(stats.completed)} hint={`${stats.failed} failed`} />
        <StatCard label="Spend" value={formatCurrency(stats.cost_usd)} />
      </div>

      <Card title="Configuration">
        <dl className="grid gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2">
          {[
            ['Max concurrent calls', String(campaign.max_concurrent_calls)],
            ['Delay between calls', `${campaign.delay_between_calls_seconds}s`],
            ['Max retries', String(campaign.max_retries)],
            ['Retry delay', `${campaign.retry_delay_minutes} min`],
            ['Calling window', `${campaign.calling_hours_start.slice(0, 5)}–${campaign.calling_hours_end.slice(0, 5)}`],
            ['Timezone', campaign.timezone],
            ['Budget cap', campaign.budget_limit_usd ? formatCurrency(campaign.budget_limit_usd) : 'None'],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 border-b border-ink-100 py-1.5">
              <dt className="text-ink-500">{label}</dt>
              <dd className="font-medium text-ink-900">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <CampaignLeadList campaignId={campaign.id} callsMade={stats.calls_made} />
    </div>
  )
}

function CampaignEditor({ onClose }: { onClose: () => void }) {
  const { data: agents } = useAgents()
  const create = useCreateCampaign()
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    name: '',
    agent_id: '',
    calling_hours_start: '10:00',
    calling_hours_end: '19:00',
    timezone: 'Asia/Kolkata',
    max_concurrent_calls: 2,
    delay_between_calls_seconds: 5,
    max_retries: 2,
    retry_delay_minutes: 180,
    budget_limit_usd: '',
  })
  const [selected, setSelected] = useState<string[]>([])

  const submit = async () => {
    setError(null)
    try {
      await create.mutateAsync({
        ...form,
        calling_hours_start: `${form.calling_hours_start}:00`,
        calling_hours_end: `${form.calling_hours_end}:00`,
        budget_limit_usd: form.budget_limit_usd ? Number(form.budget_limit_usd) : null,
        lead_ids: selected,
      })
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the campaign')
    }
  }

  return (
    <Modal open title="New campaign" onClose={onClose} wide>
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        {error && <Alert tone="error">{error}</Alert>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Campaign name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Select label="Agent" value={form.agent_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })}>
            <option value="">Choose an agent…</option>
            {agents?.items.map((agent) => (
              <option key={agent.id} value={agent.id}>{agent.name}</option>
            ))}
          </Select>
          <Field
            label="Calling hours start"
            type="time"
            value={form.calling_hours_start}
            onChange={(e) => setForm({ ...form, calling_hours_start: e.target.value })}
          />
          <Field
            label="Calling hours end"
            type="time"
            value={form.calling_hours_end}
            onChange={(e) => setForm({ ...form, calling_hours_end: e.target.value })}
            hint="Calls outside this window are never placed."
          />
          <Field
            label="Max concurrent calls"
            type="number"
            min="1"
            max="50"
            value={form.max_concurrent_calls}
            onChange={(e) => setForm({ ...form, max_concurrent_calls: Number(e.target.value) })}
            hint="Start low. This is a spend limit as much as a throughput one."
          />
          <Field
            label="Delay between calls (s)"
            type="number"
            value={form.delay_between_calls_seconds}
            onChange={(e) => setForm({ ...form, delay_between_calls_seconds: Number(e.target.value) })}
          />
          <Field
            label="Max retries"
            type="number"
            value={form.max_retries}
            onChange={(e) => setForm({ ...form, max_retries: Number(e.target.value) })}
          />
          <Field
            label="Retry delay (minutes)"
            type="number"
            value={form.retry_delay_minutes}
            onChange={(e) => setForm({ ...form, retry_delay_minutes: Number(e.target.value) })}
          />
          <Field
            label="Budget cap (USD)"
            type="number"
            step="0.01"
            value={form.budget_limit_usd}
            onChange={(e) => setForm({ ...form, budget_limit_usd: e.target.value })}
            hint="Optional. The campaign pauses itself when reached."
          />
        </div>

        <LeadPicker selected={selected} onChange={setSelected} />
      </div>

      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={submit} loading={create.isPending} disabled={!form.name || !form.agent_id}>
          Create campaign
        </Button>
      </footer>
    </Modal>
  )
}


function CampaignLeadList({ campaignId, callsMade }: { campaignId: string; callsMade: number }) {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useCampaignLeads(campaignId, page)

  return (
    <Card
      title="Who is being called"
      description="Progress through the list, so you can see who is still waiting"
      actions={
        <Link
          to={`/calls?campaign=${campaignId}`}
          className="text-xs font-medium text-brand-600 hover:text-brand-700"
        >
          View {callsMade} calls →
        </Link>
      }
      flush
    >
      {isLoading ? (
        <p className="px-5 py-8 text-center text-sm text-ink-500">Loading…</p>
      ) : !data?.items.length ? (
        <div className="px-5">
          <EmptyState
            title="No leads on this campaign"
            hint="Add leads to it before starting, or it has nothing to dial."
          />
        </div>
      ) : (
        <div className="px-5 pb-4">
          <Table headers={['Lead', 'Status', 'Attempts', 'Last attempt', 'Next attempt']}>
            {data.items.map((row) => (
              <tr key={row.id} className="hover:bg-ink-50">
                <td className="py-2.5 pl-5 pr-3">
                  <Link
                    to={`/leads?search=${row.lead_id}`}
                    className="font-medium text-ink-800 hover:text-brand-700"
                  >
                    <LeadName leadId={row.lead_id} />
                  </Link>
                </td>
                <td className="px-3 py-2.5">
                  <Badge value={row.status} />
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">{row.attempts}</td>
                <td className="px-3 py-2.5 text-xs text-ink-500">
                  {formatDateTime(row.last_attempt_at)}
                </td>
                <td className="px-3 py-2.5 text-xs text-ink-500">
                  {row.next_attempt_at ? formatDateTime(row.next_attempt_at) : '—'}
                </td>
              </tr>
            ))}
          </Table>
          <Pager page={data.page} pages={data.pages} total={data.total} onChange={setPage} />
        </div>
      )}
    </Card>
  )
}

/** Campaign membership stores only the lead id; show the name people know. */
function LeadName({ leadId }: { leadId: string }) {
  const { data } = useLead(leadId)
  return <>{data?.name ?? '…'}</>
}
