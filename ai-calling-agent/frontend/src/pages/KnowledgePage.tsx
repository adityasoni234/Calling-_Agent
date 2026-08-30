import { useRef, useState } from 'react'

import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Field } from '@/components/ui/Field'
import { TextArea } from '@/components/ui/Inputs'
import { Modal } from '@/components/ui/Modal'
import { EmptyState, Table } from '@/components/ui/Table'
import { Link } from 'react-router-dom'

import {
  useAddFaq,
  useAgents,
  useCreateKnowledgeBase,
  useDeleteDocument,
  useDocuments,
  useKnowledgeBases,
  useSearchKnowledge,
  useUploadDocument,
} from '@/hooks/api'
import { useAuthStore } from '@/stores/auth'

export function KnowledgePage() {
  const { data: bases, isLoading } = useKnowledgeBases()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const active = selectedId ?? bases?.[0]?.id ?? null

  return (
    <div className="space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Knowledge Base</h1>
          <p className="mt-1 text-sm text-ink-500">
            What the agent quotes instead of inventing. Retrieved only when a turn needs facts.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>New knowledge base</Button>
      </header>

      {isLoading ? (
        <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
      ) : !bases?.length ? (
        <Card>
          <EmptyState
            title="No knowledge base yet"
            hint="Create one, then upload documents or add FAQs."
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <nav className="space-y-1">
            {bases.map((base) => (
              <button
                key={base.id}
                type="button"
                onClick={() => setSelectedId(base.id)}
                className={`block w-full rounded-lg px-3 py-2 text-left text-sm ${
                  base.id === active
                    ? 'bg-brand-50 font-medium text-brand-700'
                    : 'text-ink-600 hover:bg-ink-100'
                }`}
              >
                {base.name}
                <span className="mt-0.5 block text-xs text-ink-400">
                  {base.document_count} docs · {base.chunk_count} chunks
                </span>
              </button>
            ))}
          </nav>

          {active && <KnowledgeBasePanel kbId={active} />}
        </div>
      )}

      {creating && <CreateBaseDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

function KnowledgeBasePanel({ kbId }: { kbId: string }) {
  const { data: documents } = useDocuments(kbId)
  const { data: agents } = useAgents()
  // Documents here do nothing until an agent points at this base — an easy
  // thing to miss, and it fails silently on a live call.
  const attached = agents?.items.filter((agent) => agent.knowledge_base_id === kbId) ?? []
  const hasDocuments = (documents?.length ?? 0) > 0
  const token = useAuthStore((state) => state.tokens?.access_token ?? null)
  const uploadDocument = useUploadDocument(kbId, token)
  const removeDocument = useDeleteDocument()
  const fileInput = useRef<HTMLInputElement>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [faqOpen, setFaqOpen] = useState(false)

  return (
    <div className="space-y-4">
      {hasDocuments && attached.length === 0 && (
        <Alert tone="warning">
          No agent uses this knowledge base yet, so nothing here reaches a call. Open{' '}
          <Link to="/agents" className="font-medium underline">
            AI Agents
          </Link>
          , edit an agent, and set its knowledge base.
        </Alert>
      )}
      {attached.length > 0 && (
        <p className="text-xs text-ink-500">
          Used by {attached.map((agent) => agent.name).join(', ')}.
        </p>
      )}

      <Card
        title="Documents"
        description="PDF, DOCX, TXT, and Markdown are extracted, chunked, and embedded."
        actions={
          <div className="flex gap-2">
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.txt,.md"
              className="hidden"
              onChange={async (event) => {
                const file = event.target.files?.[0]
                if (!file) return
                setUploadError(null)
                try {
                  await uploadDocument.mutateAsync(file)
                } catch (error) {
                  setUploadError(error instanceof Error ? error.message : 'Upload failed')
                }
                event.target.value = ''
              }}
            />
            <Button size="sm" variant="secondary" onClick={() => setFaqOpen(true)}>
              Add FAQ
            </Button>
            <Button size="sm" loading={uploadDocument.isPending} onClick={() => fileInput.current?.click()}>
              Upload
            </Button>
          </div>
        }
      >
        {uploadError && <Alert tone="error">{uploadError}</Alert>}
        {!documents?.length ? (
          <EmptyState title="Nothing here yet" hint="Upload a file or add an FAQ entry." />
        ) : (
          <Table headers={['Title', 'Type', 'Status', 'Chunks', '']}>
            {documents.map((document) => (
              <tr key={document.id} className="hover:bg-ink-50">
                <td className="px-3 py-2.5 font-medium text-ink-900">{document.title}</td>
                <td className="px-3 py-2.5 text-ink-600">{document.source_type}</td>
                <td className="px-3 py-2.5">
                  <Badge value={document.status} />
                  {document.error && (
                    <span className="ml-2 text-xs text-red-600" title={document.error}>
                      {document.error.slice(0, 40)}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">{document.chunk_count}</td>
                <td className="px-3 py-2.5 text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      if (confirm(`Delete "${document.title}"?`)) removeDocument.mutate(document.id)
                    }}
                  >
                    Delete
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <SearchPanel kbId={kbId} />
      {faqOpen && <FaqDialog kbId={kbId} onClose={() => setFaqOpen(false)} />}
    </div>
  )
}

function SearchPanel({ kbId }: { kbId: string }) {
  const [query, setQuery] = useState('')
  const search = useSearchKnowledge(kbId)

  return (
    <Card
      title="Test retrieval"
      description="Runs exactly what the agent runs, so you can see what it would be given."
    >
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (query.trim()) search.mutate(query)
        }}
      >
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask what a customer would ask…"
          className="flex-1 rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-inset ring-ink-200 focus:ring-2 focus:ring-brand-500"
        />
        <Button type="submit" loading={search.isPending}>Search</Button>
      </form>

      {search.data && (
        <div className="mt-4 space-y-2">
          {!search.data.hits.length ? (
            <p className="text-sm text-ink-500">
              Nothing matched above the similarity threshold. On a live call the agent would say it
              needs to confirm, rather than guessing.
            </p>
          ) : (
            search.data.hits.map((hit, index) => (
              <p key={index} className="rounded-lg bg-ink-50 px-3 py-2 text-sm text-ink-700">
                {hit.content}
              </p>
            ))
          )}
        </div>
      )}
    </Card>
  )
}

function CreateBaseDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const create = useCreateKnowledgeBase()

  return (
    <Modal open title="New knowledge base" onClose={onClose}>
      <div className="space-y-4">
        <Field label="Name" value={name} onChange={(event) => setName(event.target.value)} />
        <TextArea
          label="Description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button
          loading={create.isPending}
          disabled={!name.trim()}
          onClick={async () => {
            await create.mutateAsync({ name, description })
            onClose()
          }}
        >
          Create
        </Button>
      </footer>
    </Modal>
  )
}

function FaqDialog({ kbId, onClose }: { kbId: string; onClose: () => void }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const add = useAddFaq(kbId)

  return (
    <Modal open title="Add an FAQ" onClose={onClose}>
      <div className="space-y-4">
        <Field label="Question" value={question} onChange={(event) => setQuestion(event.target.value)} />
        <TextArea
          label="Answer"
          rows={5}
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          hint="Write it the way you'd want it said on a call."
        />
      </div>
      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button
          loading={add.isPending}
          disabled={question.trim().length < 3 || !answer.trim()}
          onClick={async () => {
            await add.mutateAsync({ question, answer })
            onClose()
          }}
        >
          Add
        </Button>
      </footer>
    </Modal>
  )
}
