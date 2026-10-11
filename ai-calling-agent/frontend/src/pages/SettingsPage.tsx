import { useState } from 'react'

import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Field } from '@/components/ui/Field'
import { Select } from '@/components/ui/Inputs'
import { Modal } from '@/components/ui/Modal'
import { EmptyState, Table } from '@/components/ui/Table'
import {
  useCreatePricingRate,
  usePlatformSettings,
  usePricingRates,
  useRepriceCalls,
  useUpdateOrganization,
} from '@/hooks/api'
import { ApiError, NetworkError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import type { PlatformSettings } from '@/types/api'

const PROVIDER_LABELS: Record<string, string> = {
  telephony: 'Telephony',
  stt: 'Speech to text',
  llm: 'Language model',
  tts: 'Text to speech',
  embeddings: 'Embeddings',
}

const ENV_KEYS: Record<string, Record<string, string>> = {
  plivo: { PLIVO_AUTH_ID: '', PLIVO_AUTH_TOKEN: '', PLIVO_CALLER_ID: '' },
  twilio: { TWILIO_ACCOUNT_SID: '', TWILIO_AUTH_TOKEN: '', TWILIO_CALLER_ID: '' },
  deepgram: { DEEPGRAM_API_KEY: '' },
  cartesia: { CARTESIA_API_KEY: '' },
  elevenlabs: { ELEVENLABS_API_KEY: '' },
  anthropic: { ANTHROPIC_API_KEY: '' },
  openai: { OPENAI_API_KEY: '' },
}

export function SettingsPage() {
  const { data, isLoading } = usePlatformSettings()

  if (isLoading || !data) {
    return <p className="py-10 text-center text-sm text-ink-500">Loading…</p>
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Settings"
        description="Providers, budgets, call pricing and the integration surface your CRM plugs into."
      />

      {data.using_mocks && (
        <Alert tone="warning">
          <strong>Running on mock providers.</strong> The full pipeline works end to end, but no real
          phone calls are placed and no vendor is billed. Set the provider keys in <code>.env</code>{' '}
          and restart to go live.
        </Alert>
      )}

      <Card title="Providers" description="Credentials are read server-side only and never sent to the browser.">
        <Table headers={['Capability', 'Selected', 'Credentials', 'Available']}>
          {Object.entries(data.providers).map(([kind, provider]) => (
            <tr key={kind}>
              <td className="px-3 py-2.5 font-medium text-ink-900">
                {PROVIDER_LABELS[kind] ?? kind}
              </td>
              <td className="px-3 py-2.5">
                <Badge value={provider.selected} tone={provider.is_mock ? 'amber' : 'blue'} />
              </td>
              <td className="px-3 py-2.5">
                {provider.is_mock ? (
                  <span className="text-xs text-ink-500">not required</span>
                ) : provider.configured ? (
                  <Badge value="configured" tone="green" />
                ) : (
                  <span className="text-xs text-red-600">
                    missing {Object.keys(ENV_KEYS[provider.selected] ?? {}).join(', ') || 'API key'}
                  </span>
                )}
              </td>
              <td className="px-3 py-2.5 text-xs text-ink-500">{provider.available.join(', ')}</td>
            </tr>
          ))}
        </Table>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Platform">
          <dl className="space-y-2 text-sm">
            {[
              ['Organization', data.organization_name],
              ['Timezone', data.organization_timezone],
              ['LLM model', data.llm_model],
              ['Embedding model', data.embedding_model],
              ['Webhook base URL', data.public_base_url],
              ['Global concurrent-call cap', String(data.max_global_concurrent_calls)],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 border-b border-ink-100 pb-1.5">
                <dt className="text-ink-500">{label}</dt>
                <dd className="truncate font-medium text-ink-900">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>

        <BudgetCard settings={data} />
      </div>

      <PricingSection />
    </div>
  )
}

function PricingSection() {
  const { data: rates } = usePricingRates()
  const reprice = useRepriceCalls()
  const [adding, setAdding] = useState(false)

  return (
    <Card
      title="Pricing rates"
      description="No rate ships with this platform. Enter what you read on the vendor's rate card, with the source."
      actions={
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            loading={reprice.isPending}
            onClick={() => reprice.mutate()}
          >
            Reprice past calls
          </Button>
          <Button size="sm" onClick={() => setAdding(true)}>Add rate</Button>
        </div>
      }
    >
      {reprice.data && (
        <div className="mb-3">
          <Alert tone="success">
            Priced {reprice.data.lines_priced} usage line(s) across {reprice.data.calls_updated}{' '}
            call(s), adding ${reprice.data.cost_added_usd.toFixed(4)}.
          </Alert>
        </div>
      )}
      {!rates?.length ? (
        <EmptyState
          title="No rates recorded"
          hint="Until a rate exists, calls using that component are flagged as incomplete rather than priced with a guess."
        />
      ) : (
        <Table headers={['Component', 'Provider', 'Model', 'Unit', 'Rate', 'Verified', 'Source']}>
          {rates.map((rate) => (
            <tr key={rate.id}>
              <td className="px-3 py-2.5 font-medium text-ink-900">{rate.component}</td>
              <td className="px-3 py-2.5 text-ink-600">{rate.provider}</td>
              <td className="px-3 py-2.5 text-ink-600">{rate.model ?? 'any'}</td>
              <td className="px-3 py-2.5 text-ink-600">{rate.unit}</td>
              <td className="px-3 py-2.5 tabular-nums text-ink-900">
                {rate.rate} {rate.currency}
              </td>
              <td className="px-3 py-2.5 text-xs text-ink-500">{formatDateTime(rate.verified_at)}</td>
              <td className="max-w-48 truncate px-3 py-2.5 text-xs">
                <a
                  href={rate.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-600 hover:text-brand-700"
                >
                  {rate.source_url}
                </a>
              </td>
            </tr>
          ))}
        </Table>
      )}

      {adding && <RateDialog onClose={() => setAdding(false)} />}
    </Card>
  )
}

function RateDialog({ onClose }: { onClose: () => void }) {
  const create = useCreatePricingRate()
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    component: 'telephony',
    provider: 'plivo',
    model: '',
    unit: 'minute',
    rate: '',
    currency: 'USD',
    region: '',
    source_url: '',
    verified_at: new Date().toISOString().slice(0, 10),
  })

  const submit = async () => {
    setError(null)
    try {
      await create.mutateAsync({
        ...form,
        model: form.model || null,
        region: form.region || null,
        rate: Number(form.rate),
        verified_at: new Date(form.verified_at).toISOString(),
      })
      onClose()
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not save the rate')
    }
  }

  return (
    <Modal open title="Add a verified rate" onClose={onClose}>
      <div className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <p className="text-xs text-ink-500">
          Enter the rate for <em>your</em> destination and volume tier — India voice and
          Indian-language ASR are often priced differently from the default quote.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="Component"
            value={form.component}
            onChange={(event) => setForm({ ...form, component: event.target.value })}
          >
            {['telephony', 'stt', 'llm', 'tts', 'embedding', 'infra'].map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </Select>
          <Field
            label="Provider"
            value={form.provider}
            onChange={(event) => setForm({ ...form, provider: event.target.value })}
            hint="Must match the adapter name, e.g. plivo, deepgram."
          />
          <Field
            label="Model (optional)"
            value={form.model}
            onChange={(event) => setForm({ ...form, model: event.target.value })}
          />
          <Select
            label="Unit"
            value={form.unit}
            onChange={(event) => setForm({ ...form, unit: event.target.value })}
          >
            {[
              'minute', 'second', 'call', 'character', 'character_1k',
              'token_in', 'token_out', 'token_in_1k', 'token_out_1k',
            ].map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </Select>
          <Field
            label="Rate"
            type="number"
            step="0.000001"
            value={form.rate}
            onChange={(event) => setForm({ ...form, rate: event.target.value })}
          />
          <Field
            label="Region (optional)"
            value={form.region}
            onChange={(event) => setForm({ ...form, region: event.target.value })}
            hint="e.g. IN"
          />
        </div>

        <Field
          label="Source URL"
          value={form.source_url}
          onChange={(event) => setForm({ ...form, source_url: event.target.value })}
          hint="The page you read this rate on. Required."
        />
        <Field
          label="Verified on"
          type="date"
          value={form.verified_at}
          onChange={(event) => setForm({ ...form, verified_at: event.target.value })}
        />
      </div>

      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={submit} loading={create.isPending} disabled={!form.rate || !form.source_url}>
          Save rate
        </Button>
      </footer>
    </Modal>
  )
}


function BudgetCard({ settings }: { settings: PlatformSettings }) {
  const update = useUpdateOrganization()
  const [daily, setDaily] = useState(String(settings.daily_budget_usd ?? ''))
  const [monthly, setMonthly] = useState(String(settings.monthly_budget_usd ?? ''))
  const [concurrent, setConcurrent] = useState(String(settings.max_concurrent_calls ?? ''))
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const budget = settings.budget
  const spend = (key: string) => Number(budget[key] ?? 0).toFixed(4)

  const save = async () => {
    setError(null)
    setSaved(false)
    try {
      await update.mutateAsync({
        // Blank clears the override and falls back to the deployment default.
        daily_budget_usd: daily.trim() === '' ? null : Number(daily),
        monthly_budget_usd: monthly.trim() === '' ? null : Number(monthly),
        max_concurrent_calls: concurrent.trim() === '' ? null : Number(concurrent),
      })
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not save the limits')
    }
  }

  return (
    <Card
      title="Spend limits"
      description="Checked before a call is placed, never after. An in-flight call cannot be un-billed."
    >
      {error && <Alert tone="error">{error}</Alert>}
      {saved && <Alert tone="success">Limits saved — they apply to the next call.</Alert>}

      <dl className="mb-4 grid grid-cols-2 gap-3 rounded-xl bg-ink-50 px-4 py-3 text-sm">
        <div>
          <dt className="text-2xs uppercase tracking-wider text-ink-400">Spent today</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-ink-900">${spend('daily_spend')}</dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wider text-ink-400">Spent this month</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-ink-900">
            ${spend('monthly_spend')}
          </dd>
        </div>
      </dl>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="Daily limit (USD)"
          type="number"
          min="0"
          value={daily}
          onChange={(event) => setDaily(event.target.value)}
          placeholder="no cap"
        />
        <Field
          label="Monthly limit (USD)"
          type="number"
          min="0"
          value={monthly}
          onChange={(event) => setMonthly(event.target.value)}
          placeholder="no cap"
        />
        <Field
          label="Max calls at once"
          type="number"
          min="1"
          value={concurrent}
          onChange={(event) => setConcurrent(event.target.value)}
          placeholder="deployment default"
        />
      </div>
      <p className="mt-2 text-xs text-ink-500">
        Leave blank to use the deployment default. Enter 0 for no cap — not recommended once
        campaigns run unattended.
      </p>

      <div className="mt-4 flex items-center gap-3">
        <Button size="sm" onClick={save} loading={update.isPending}>
          Save limits
        </Button>
        {(budget.daily_exceeded || budget.monthly_exceeded) && (
          <span className="text-xs font-medium text-red-600">
            Limit reached — new calls are blocked.
          </span>
        )}
      </div>
    </Card>
  )
}
