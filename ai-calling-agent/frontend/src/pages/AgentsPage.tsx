import { useState } from 'react'

import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Field } from '@/components/ui/Field'
import { Disclosure } from '@/components/ui/Disclosure'
import { ListField, Select, TextArea } from '@/components/ui/Inputs'
import { Modal } from '@/components/ui/Modal'
import { EmptyState, Table } from '@/components/ui/Table'
import { Link } from 'react-router-dom'

import {
  useAgentPrompt,
  useAgents,
  useDeleteAgent,
  useGenerateAgent,
  useKnowledgeBases,
  usePlaceCall,
  useSaveAgent,
} from '@/hooks/api'
import { ApiError, NetworkError } from '@/lib/api'
import type { Agent } from '@/types/api'

const BLANK: Partial<Agent> = {
  name: '',
  role_title: 'Sales Executive',
  company_name: '',
  personality: 'Warm, concise, and respectful.',
  primary_objective: '',
  secondary_objectives: [],
  language: 'auto',
  greeting: '',
  system_instructions: '',
  forbidden_rules: [],
  qualification_questions: [],
  ending_rules: [],
  objection_handling: [],
  transfer_rules: { enabled: false, phone_number: '', conditions: [] },
  voice_config: { voice_id: '', language: 'en', speed: 1 },
  temperature: 0.6,
  max_call_seconds: 420,
  silence_prompt_ms: 6000,
  silence_hangup_ms: 12000,
  interruptible: true,
  ask_language_preference: true,
  record_calls: true,
  knowledge_base_id: null,
  is_active: true,
}

export function AgentsPage() {
  const { data, isLoading } = useAgents()
  const { data: bases } = useKnowledgeBases()
  const remove = useDeleteAgent()

  const [editing, setEditing] = useState<Partial<Agent> | null>(null)
  const [promptFor, setPromptFor] = useState<string | null>(null)
  const [testFor, setTestFor] = useState<Agent | null>(null)

  return (
    <div className="space-y-5">
      <PageHeader
        title="AI Agents"
        description="Who calls your leads, what they ask, and what they must never claim."
        actions={<Button onClick={() => setEditing({ ...BLANK })}>New agent</Button>}
      />

      <Card>
        {isLoading ? (
          <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
        ) : !data?.items.length ? (
          <EmptyState
            title="No agents yet"
            hint="An agent is the script and personality for a call. Describe your business in a few lines and it writes the whole thing for you."
            action={<Button onClick={() => setEditing({ ...BLANK })}>Create your first agent</Button>}
          />
        ) : (
          <Table headers={['Name', 'Role', 'Language', 'Voice', 'Status', '']}>
            {data.items.map((agent) => (
              <tr key={agent.id} className="hover:bg-ink-50">
                <td className="px-3 py-2.5 font-medium text-ink-900">{agent.name}</td>
                <td className="px-3 py-2.5 text-ink-600">
                  {agent.role_title}
                  {agent.company_name && <span className="text-ink-400"> · {agent.company_name}</span>}
                </td>
                <td className="px-3 py-2.5">
                  <Badge value={agent.language} tone="purple" />
                </td>
                <td className="px-3 py-2.5 text-ink-600">
                  {agent.voice_config?.voice_id || <span className="text-ink-400">not set</span>}
                </td>
                <td className="px-3 py-2.5">
                  <Badge value={agent.is_active ? 'active' : 'inactive'} tone={agent.is_active ? 'green' : 'neutral'} />
                </td>
                <td className="px-3 py-2.5 text-right">
                  <div className="flex justify-end gap-1.5">
                    <Button size="sm" variant="secondary" onClick={() => setTestFor(agent)}>
                      Test call
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setPromptFor(agent.id)}>
                      Prompt
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(agent)}>
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        if (confirm(`Delete agent "${agent.name}"?`)) remove.mutate(agent.id)
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {editing && (
        <AgentEditor
          agent={editing}
          knowledgeBases={bases ?? []}
          onClose={() => setEditing(null)}
        />
      )}
      {promptFor && <PromptViewer agentId={promptFor} onClose={() => setPromptFor(null)} />}
      {testFor && <TestCallDialog agent={testFor} onClose={() => setTestFor(null)} />}
    </div>
  )
}

/**
 * What the agent will actually do, in sentences.
 *
 * A new user cannot check twenty-seven form fields, but they can read four
 * paragraphs and say "that's wrong, she shouldn't ask that". This is the
 * review step; the form underneath is for people who want it.
 */
function PlainReview({ form }: { form: Partial<Agent> }) {
  const lines: { heading: string; body: string[] }[] = [
    {
      heading: 'She opens with',
      body: [form.greeting ? `"${form.greeting}"` : 'Nothing set yet.'],
    },
    {
      heading: 'She is trying to',
      body: [form.primary_objective || 'Nothing set yet.'],
    },
    {
      heading: 'She will ask',
      body: (form.qualification_questions ?? []).length
        ? (form.qualification_questions as string[])
        : ['No questions yet.'],
    },
    {
      heading: 'She will never',
      body: (form.forbidden_rules ?? []).length
        ? (form.forbidden_rules as string[])
        : ['No limits set — worth adding some.'],
    },
  ]

  return (
    <div className="space-y-4 rounded-xl bg-ink-50 p-5 ring-1 ring-ink-200/70">
      {lines.map((section) => (
        <div key={section.heading}>
          <p className="text-2xs font-medium uppercase tracking-[0.1em] text-ink-400">
            {section.heading}
          </p>
          <ul className="mt-1.5 space-y-1">
            {section.body.map((item, index) => (
              <li key={index} className="text-sm leading-relaxed text-ink-800">
                {section.body.length > 1 && <span className="mr-1.5 text-ink-400">·</span>}
                {item}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function AgentEditor({
  agent,
  knowledgeBases,
  onClose,
}: {
  agent: Partial<Agent>
  knowledgeBases: { id: string; name: string }[]
  onClose: () => void
}) {
  const [form, setForm] = useState<Partial<Agent>>(agent)
  const [error, setError] = useState<string | null>(null)
  const [brief, setBrief] = useState('')
  const [generated, setGenerated] = useState<string | null>(null)
  // A new agent starts in plain-language mode: describe it, read it back,
  // save. The full form is opt-in, not the default.
  const [drafted, setDrafted] = useState(false)
  const [showForm, setShowForm] = useState(Boolean(agent.id))
  const save = useSaveAgent(agent.id)
  const generate = useGenerateAgent()

  const runGenerate = async () => {
    setError(null)
    setGenerated(null)
    try {
      const result = await generate.mutateAsync({ brief, company_name: form.company_name })
      // Merge over the current form so voice, timers and knowledge base survive.
      setForm((current) => ({ ...current, ...result.draft }))
      setGenerated(result.notes)
      setDrafted(true)
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not draft the agent')
    }
  }

  const set = <K extends keyof Agent>(key: K, value: Agent[K]) =>
    setForm((current) => ({ ...current, [key]: value }))

  const submit = async () => {
    setError(null)
    // The API rejects unknown fields on PATCH, and these are server-owned.
    const { id, organization_id, created_at, ...body } = form as Agent
    void id
    void organization_id
    void created_at
    try {
      await save.mutateAsync(body)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not save the agent')
    }
  }

  return (
    <Modal open title={agent.id ? `Edit ${agent.name}` : 'New agent'} onClose={onClose} wide>
      <div className="max-h-[72vh] space-y-4 overflow-y-auto pr-1">
        {error && <Alert tone="error">{error}</Alert>}

        {!agent.id && (
          <div className="rounded-xl bg-brand-50 p-4 ring-1 ring-brand-200">
            <p className="text-sm font-semibold text-ink-900">Start by describing it</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-600">
              Who you are, who you're calling, and what a good call achieves. A sentence or
              two is enough — but if you already have a full brief or prompt written, paste
              the whole thing. The detail gets used, not summarised away.
            </p>
            <TextArea
              label=""
              rows={6}
              className="mt-3"
              value={brief}
              placeholder="We're a stock advisory. Call people who filled our website form, find out what they invest in today, and book a fifteen minute demo. Be respectful, never push."
              onChange={(event) => setBrief(event.target.value)}
            />
            <div className="mt-2.5 flex items-center gap-3">
              <Button
                size="sm"
                loading={generate.isPending}
                disabled={brief.trim().length < 20}
                onClick={runGenerate}
              >
                Write it for me
              </Button>
              <span className="text-2xs text-ink-500">
                {brief.trim().length < 20
                  ? 'A sentence or two is enough'
                  : brief.length > 1200
                    ? 'Detailed brief — this will take a few seconds longer'
                    : 'Takes about ten seconds'}
              </span>
            </div>
          </div>
        )}

        {generated && <Alert tone="warning">{generated}</Alert>}

        {!agent.id && drafted && (
          <div className="space-y-3">
            <div>
              <p className="font-display text-base text-ink-900">
                Here is what {form.name || 'your agent'} will do
              </p>
              <p className="mt-1 text-xs leading-relaxed text-ink-500">
                Read it through. If something is wrong, open the details below and change it —
                or describe it differently and write it again.
              </p>
            </div>
            <PlainReview form={form} />
            {!showForm && (
              <button
                type="button"
                onClick={() => setShowForm(true)}
                className="text-xs font-medium text-brand-700 underline underline-offset-2 hover:text-brand-800"
              >
                Let me change the details myself
              </button>
            )}
          </div>
        )}

        {/* The form. Hidden on a new agent until someone asks for it: a
            twenty-seven field wall is where a non-technical user gives up. */}
        <div className={showForm ? 'contents' : 'hidden'}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Agent name"
            value={form.name ?? ''}
            onChange={(e) => set('name', e.target.value)}
            placeholder="Riya"
            hint="The first name they'll hear."
          />
          <Field
            label="Job title"
            value={form.role_title ?? ''}
            onChange={(e) => set('role_title', e.target.value)}
            placeholder="Sales Executive"
          />
          <Field
            label="Company"
            value={form.company_name ?? ''}
            onChange={(e) => set('company_name', e.target.value)}
          />
          <Select
            label="Language"
            value={form.language ?? 'auto'}
            onChange={(e) => set('language', e.target.value as Agent['language'])}
            hint="Auto mirrors whatever the customer speaks."
          >
            <option value="auto">Auto — match the customer</option>
            <option value="en">English only</option>
            <option value="hi">Hindi only</option>
            <option value="hinglish">Hinglish</option>
          </Select>
        </div>

        <TextArea
          label="What is this call for?"
          rows={2}
          value={form.primary_objective ?? ''}
          onChange={(e) => set('primary_objective', e.target.value)}
          hint="One goal. Everything the agent says works towards this."
        />

        <TextArea
          label="Opening line"
          rows={2}
          value={form.greeting ?? ''}
          onChange={(e) => set('greeting', e.target.value)}
          hint="Spoken in the first two seconds. Leave blank to generate one. Use {name} for the lead's name."
        />

        <Disclosure
          title="What to say"
          description="Questions to ask, objections to expect, and what never to claim"
          summary={`${form.qualification_questions?.length ?? 0} questions · ${form.forbidden_rules?.length ?? 0} rules`}
        >
          <TextArea
            label="Personality"
            rows={2}
            value={form.personality ?? ''}
            onChange={(e) => set('personality', e.target.value)}
          />
          <ListField
            label="Questions to work in"
            value={form.qualification_questions ?? []}
            onChange={(next) => set('qualification_questions', next)}
            hint="One per line. Asked one at a time, never read as a list."
          />
          <ListField
            label="Never say this"
            value={form.forbidden_rules ?? []}
            onChange={(next) => set('forbidden_rules', next)}
            hint="One per line. Claims your business cannot make — this is what keeps you out of trouble."
          />
          <ListField
            label="When to end the call"
            value={form.ending_rules ?? []}
            onChange={(next) => set('ending_rules', next)}
          />
          <ListField
            label="Other goals"
            value={form.secondary_objectives ?? []}
            onChange={(next) => set('secondary_objectives', next)}
          />
          <TextArea
            label="Anything else"
            rows={3}
            value={form.system_instructions ?? ''}
            onChange={(e) => set('system_instructions', e.target.value)}
            hint="Free-form instructions appended to the prompt."
          />
        </Disclosure>

        <Disclosure
          title="Voice, timing and limits"
          description="Most people never need to change these"
          summary={`${form.voice_config?.voice_id || 'no voice set'} · ${form.max_call_seconds ?? 420}s max`}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Voice ID"
              value={form.voice_config?.voice_id ?? ''}
              onChange={(e) => set('voice_config', { ...form.voice_config, voice_id: e.target.value })}
              hint="Leave blank to use the default voice. Your provider gives you this if you want a specific one."
            />
            <Select
              label="Facts she can quote"
              value={form.knowledge_base_id ?? ''}
              onChange={(e) => set('knowledge_base_id', e.target.value || null)}
              hint="Facts to quote instead of guessing."
            >
              <option value="">None</option>
              {knowledgeBases.map((base) => (
                <option key={base.id} value={base.id}>
                  {base.name}
                </option>
              ))}
            </Select>
            <Field
              label="End the call after (seconds)"
              type="number"
              value={form.max_call_seconds ?? 420}
              onChange={(e) => set('max_call_seconds', Number(e.target.value))}
              hint="A hard cap, so a stuck call cannot run up cost."
            />
            <Field
              label="How much she improvises"
              type="number"
              step="0.1"
              min="0"
              max="1.5"
              value={form.temperature ?? 0.6}
              onChange={(e) => set('temperature', Number(e.target.value))}
              hint="Lower sticks to the script. 0.6 is a good default."
            />
            <Field
              label="If they go quiet, check in after (seconds)"
              type="number"
              value={form.silence_prompt_ms ?? 6000}
              onChange={(e) => set('silence_prompt_ms', Number(e.target.value))}
            />
            <Field
              label="If still no answer, hang up after (seconds)"
              type="number"
              value={form.silence_hangup_ms ?? 12000}
              onChange={(e) => set('silence_hangup_ms', Number(e.target.value))}
            />
          </div>

          <div className="space-y-2.5 rounded-xl bg-ink-50 px-4 py-3">
            {[
              ['interruptible', 'Let the customer interrupt', 'Stops talking the moment they speak.'],
              ['ask_language_preference', 'Ask which language they prefer', 'Costs one turn, improves the rest of the call.'],
              ['record_calls', 'Record calls', 'The agent announces it once, briefly.'],
              ['is_active', 'Active', 'Inactive agents cannot be dialled.'],
            ].map(([key, label, detail]) => (
              <label key={key} className="flex cursor-pointer items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={(form[key as keyof Agent] as boolean) ?? true}
                  onChange={(e) => set(key as keyof Agent, e.target.checked as never)}
                  className="mt-0.5 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                />
                <span>
                  <span className="block text-ink-800">{label}</span>
                  <span className="block text-2xs text-ink-500">{detail}</span>
                </span>
              </label>
            ))}
          </div>

          <label className="flex cursor-pointer items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              checked={form.transfer_rules?.enabled ?? false}
              onChange={(e) => set('transfer_rules', { ...form.transfer_rules, enabled: e.target.checked })}
              className="mt-0.5 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            <span>
              <span className="block text-ink-800">Allow transfer to a human</span>
              <span className="block text-2xs text-ink-500">
                The agent hands off when it cannot help.
              </span>
            </span>
          </label>
          {form.transfer_rules?.enabled && (
            <Field
              label="Pass the call to this number when asked"
              value={form.transfer_rules?.phone_number ?? ''}
              onChange={(e) =>
                set('transfer_rules', { ...form.transfer_rules, phone_number: e.target.value })
              }
            />
          )}
        </Disclosure>
        </div>
      </div>

      <footer className="mt-4 flex items-center justify-end gap-2 border-t border-ink-200/70 pt-4">
        {!agent.id && !drafted && (
          <p className="mr-auto text-xs text-ink-500">
            Describe your business above — everything else is written for you.
          </p>
        )}
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={submit} loading={save.isPending} disabled={!agent.id && !drafted}>
          {agent.id ? 'Save changes' : 'Save agent'}
        </Button>
      </footer>
    </Modal>
  )
}

function PromptViewer({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  const { data, isLoading } = useAgentPrompt(agentId)
  return (
    <Modal open title="The exact instructions she receives" onClose={onClose} wide>
      {isLoading || !data ? (
        <p className="py-6 text-center text-sm text-ink-500">Building…</p>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-ink-500">
            Built from this agent's configuration. Roughly {data.estimated_tokens} tokens, sent as a
            cached prefix on every turn.
          </p>
          <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded-lg bg-ink-900 p-4 text-xs leading-relaxed text-ink-100">
            {data.system_prompt}
          </pre>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Opening line</p>
            <p className="mt-1 text-sm text-ink-700">{data.greeting}</p>
          </div>
        </div>
      )}
    </Modal>
  )
}


function TestCallDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const [number, setNumber] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [placed, setPlaced] = useState(false)
  const place = usePlaceCall()

  const submit = async () => {
    setError(null)
    try {
      await place.mutateAsync({ agent_id: agent.id, to_number: number })
      setPlaced(true)
    } catch (err) {
      setError(err instanceof ApiError || err instanceof NetworkError ? err.message : 'Could not place the call')
    }
  }

  return (
    <Modal open title={`Test ${agent.name}`} onClose={onClose}>
      {placed ? (
        <div className="space-y-3">
          <Alert tone="success">Calling {number} now — answer and talk to {agent.name}.</Alert>
          <p className="text-sm text-ink-600">
            The transcript, summary and cost appear under{' '}
            <Link to="/calls" className="font-medium text-brand-600">
              Calls
            </Link>{' '}
            once it ends.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <p className="text-sm text-ink-600">
            Call your own phone to hear how {agent.name} sounds. No lead is created.
          </p>
          <Field
            label="Your phone number"
            value={number}
            onChange={(event) => setNumber(event.target.value)}
            placeholder="+919876543210"
            hint="Include the country code. On a trial carrier account this must be a verified number."
          />
        </div>
      )}
      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>
          {placed ? 'Done' : 'Cancel'}
        </Button>
        {!placed && (
          <Button onClick={submit} loading={place.isPending} disabled={number.trim().length < 8}>
            Call me
          </Button>
        )}
      </footer>
    </Modal>
  )
}
