import { useState } from 'react'

import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Field } from '@/components/ui/Field'
import {
  useApiKeys,
  useCreateApiKey,
  useCreateWebhook,
  useDeleteWebhook,
  useRevokeApiKey,
  useTestWebhook,
  useWebhookEvents,
  useWebhooks,
} from '@/hooks/api'
import { formatDateTime } from '@/lib/format'

/**
 * Connect any CRM: a key to call in, a signed webhook to be called back on.
 *
 * Both secrets are shown exactly once. The UI has to make that unmissable,
 * because the alternative is a user who closes the panel and has to start over.
 */
export function IntegrationsCard() {
  return (
    <div className="space-y-5">
      <ApiKeys />
      <Webhooks />
    </div>
  )
}

function CopyOnce({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Alert tone="success">
      <p className="font-medium">{label}</p>
      <p className="mt-1 text-xs">
        This is shown once and cannot be recovered. Copy it somewhere safe now.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-white px-2.5 py-1.5 font-mono text-xs ring-1 ring-emerald-200">
          {value}
        </code>
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value)
              setCopied(true)
            } catch {
              // Clipboard can be blocked; the value is on screen to select.
            }
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </Alert>
  )
}

function ApiKeys() {
  const { data: keys } = useApiKeys()
  const create = useCreateApiKey()
  const revoke = useRevokeApiKey()
  const [name, setName] = useState('')
  const [fresh, setFresh] = useState<string | null>(null)

  return (
    <Card
      title="API keys"
      description="Let your CRM call this platform without a browser login. A key reaches the same API the dashboard uses, scoped to your organization."
    >
      <div className="space-y-3">
        {fresh && <CopyOnce label="Your new API key" value={fresh} />}

        <div className="flex gap-2">
          <Field
            label="Key name"
            className="flex-1"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Zoho CRM"
            hint="Name it after what will use it, so you know what breaks if you revoke it."
          />
          <div className="self-end pb-[1.35rem]">
            <Button
              onClick={async () => {
                const created = await create.mutateAsync(name.trim() || 'Untitled key')
                setFresh(created.key)
                setName('')
              }}
              loading={create.isPending}
              disabled={!name.trim()}
            >
              Create key
            </Button>
          </div>
        </div>

        {(keys ?? []).length === 0 ? (
          <p className="py-2 text-xs text-ink-500">No keys yet.</p>
        ) : (
          <ul className="divide-y divide-ink-100 rounded-xl ring-1 ring-ink-200">
            {(keys ?? []).map((key) => (
              <li key={key.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-ink-900">{key.name}</span>
                  <span className="ml-2 font-mono text-xs text-ink-400">{key.prefix}…</span>
                </span>
                <span className="text-xs text-ink-500">
                  {key.last_used_at ? `used ${formatDateTime(key.last_used_at)}` : 'never used'}
                </span>
                {key.revoked_at ? (
                  <Badge value="revoked" tone="red" />
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      if (
                        confirm(
                          `Revoke "${key.name}"?\n\nAnything using this key stops working immediately.`,
                        )
                      ) {
                        revoke.mutate(key.id)
                      }
                    }}
                  >
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

function Webhooks() {
  const { data: endpoints } = useWebhooks()
  const { data: events } = useWebhookEvents()
  const create = useCreateWebhook()
  const remove = useDeleteWebhook()
  const test = useTestWebhook()

  const [url, setUrl] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [secret, setSecret] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  return (
    <Card
      title="Webhooks"
      description="We POST to your CRM when a call finishes or a lead qualifies, so it never has to poll. Every delivery is signed."
    >
      <div className="space-y-3">
        {error && <Alert tone="error">{error}</Alert>}
        {note && <Alert tone="info">{note}</Alert>}
        {secret && <CopyOnce label="Signing secret for this webhook" value={secret} />}

        <Field
          label="Endpoint URL"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://your-crm.com/hooks/calling-agent"
          hint="Must be https — payloads carry lead names and phone numbers."
        />

        <div>
          <p className="text-xs font-medium text-ink-600">Events</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(events ?? []).map((event) => {
              const on = chosen.includes(event)
              return (
                <button
                  key={event}
                  type="button"
                  onClick={() =>
                    setChosen(on ? chosen.filter((x) => x !== event) : [...chosen, event])
                  }
                  className={`rounded-lg px-2.5 py-1 text-2xs font-medium transition-colors ${
                    on
                      ? 'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200'
                      : 'text-ink-500 ring-1 ring-inset ring-ink-200 hover:bg-ink-50'
                  }`}
                >
                  {event}
                </button>
              )
            })}
          </div>
          <p className="mt-1.5 text-xs text-ink-400">
            Choose none to receive everything.
          </p>
        </div>

        <Button
          onClick={async () => {
            setError(null)
            setNote(null)
            try {
              const created = await create.mutateAsync({ url: url.trim(), events: chosen })
              setSecret(created.secret)
              setUrl('')
              setChosen([])
            } catch (err) {
              setError(err instanceof Error ? err.message : 'Could not add the webhook')
            }
          }}
          loading={create.isPending}
          disabled={!url.trim()}
        >
          Add webhook
        </Button>

        {(endpoints ?? []).length === 0 ? (
          <p className="py-2 text-xs text-ink-500">No webhooks yet.</p>
        ) : (
          <ul className="divide-y divide-ink-100 rounded-xl ring-1 ring-ink-200">
            {(endpoints ?? []).map((endpoint) => (
              <li key={endpoint.id} className="px-3 py-2.5 text-sm">
                <div className="flex items-center gap-3">
                  <span className="min-w-0 flex-1 truncate font-medium text-ink-900">
                    {endpoint.url}
                  </span>
                  <Badge value={endpoint.is_active ? 'active' : 'inactive'} />
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={test.isPending}
                    onClick={async () => {
                      const result = await test.mutateAsync(endpoint.id)
                      setNote(result.message)
                    }}
                  >
                    Send test
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      if (confirm(`Delete this webhook?\n\n${endpoint.url}`)) {
                        remove.mutate(endpoint.id)
                      }
                    }}
                  >
                    Delete
                  </Button>
                </div>
                <p className="mt-1 text-xs text-ink-400">
                  {endpoint.events.length ? endpoint.events.join(', ') : 'all events'}
                  {endpoint.last_delivery_at &&
                    ` · last delivery ${formatDateTime(endpoint.last_delivery_at)}`}
                </p>
                {!endpoint.is_active && endpoint.last_error && (
                  <p className="mt-1 text-xs text-red-600">
                    Disabled after repeated failures: {endpoint.last_error}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}
