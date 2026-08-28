import { PhasePlaceholder } from '@/components/PhasePlaceholder'

export function AgentsPage() {
  return (
    <PhasePlaceholder
      title="AI Agents"
      phase="Phase 2"
      summary="Configure the persona, objectives, and voice of each calling agent."
      scope={[
        'Name, role, company, personality, and primary/secondary objectives',
        'Language settings for English, Hindi, and Hinglish',
        'Greeting, system instructions, and forbidden statements',
        'Qualification questions, objection handling, and ending rules',
        'Voice configuration and knowledge-base assignment',
        'Prompts built dynamically from this configuration',
      ]}
    />
  )
}

export function LeadsPage() {
  return (
    <PhasePlaceholder
      title="Leads"
      phase="Phase 7"
      summary="The contact records your agents call, with status and score."
      scope={[
        'Manual creation and CSV import with validation',
        'Search, filter, and pagination',
        'Campaign assignment and call history',
        'Status, interest level, lead score, and notes',
      ]}
    />
  )
}

export function CampaignsPage() {
  return (
    <PhasePlaceholder
      title="Campaigns"
      phase="Phase 7"
      summary="Batch outbound calling with hard limits on concurrency."
      scope={[
        'Agent selection and lead list assignment',
        'Calling hours enforced in the organization timezone',
        'Retry rules and delay between calls',
        'Configurable concurrency, never uncontrolled parallel dialing',
        'Start, pause, and stop controls',
      ]}
    />
  )
}

export function CallsPage() {
  return (
    <PhasePlaceholder
      title="Calls"
      phase="Phase 3"
      summary="Every call, its transcript, and what it cost."
      scope={[
        'Lifecycle: initiated, ringing, in progress, completed, failed, no answer, busy, canceled',
        'Start/end time, duration, and recording reference',
        'Full transcript with per-turn timing',
        'Summary and extracted structured data (Phase 8)',
        'Estimated cost broken down by component (Phase 9)',
      ]}
    />
  )
}

export function KnowledgePage() {
  return (
    <PhasePlaceholder
      title="Knowledge Base"
      phase="Phase 6"
      summary="Business knowledge the agent quotes instead of inventing."
      scope={[
        'Upload PDF, DOCX, TXT, and Markdown; add FAQs manually',
        'Extract → chunk → embed → store in pgvector',
        'Retrieval only when a turn actually needs facts',
        'Agent must decline rather than hallucinate when nothing matches',
      ]}
    />
  )
}

export function SettingsPage() {
  return (
    <PhasePlaceholder
      title="Settings"
      phase="Phase 2 onward"
      summary="Organization, provider, and budget configuration."
      scope={[
        'Organization profile and timezone',
        'Provider selection for telephony, STT, LLM, and TTS',
        'API credentials stored server-side only, never sent to the browser',
        'Budget warnings and hard caps (Phase 9)',
        'Team members and roles',
      ]}
    />
  )
}
