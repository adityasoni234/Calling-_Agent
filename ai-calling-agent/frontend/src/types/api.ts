export type UserRole = 'owner' | 'admin' | 'operator' | 'viewer'

export interface Organization {
  id: string
  name: string
  slug: string
  timezone: string
  is_active: boolean
  created_at: string
}

export interface User {
  id: string
  organization_id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

export interface UserWithOrganization extends User {
  organization: Organization
}

/** Login returns a bare user; /auth/me enriches it with the organization. */
export type AuthUser = User & { organization?: Organization }

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface AuthResponse {
  user: User
  tokens: TokenPair
}

export interface MessageResponse {
  message: string
}

export interface HealthResponse {
  status: string
  app: string
  environment: string
  version: string
  database: string
}

/** Every error the API returns has this shape -- see backend `app/core/errors.py`. */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: { field: string; message: string; type: string }[] | unknown
  }
}

// --- pagination -------------------------------------------------------

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// --- agents -----------------------------------------------------------

export type AgentLanguage = 'en' | 'hi' | 'hinglish' | 'auto'

export interface ObjectionPair {
  objection: string
  response: string
}

export interface Agent {
  id: string
  organization_id: string
  name: string
  role_title: string
  company_name: string
  personality: string
  primary_objective: string
  secondary_objectives: string[]
  language: AgentLanguage
  greeting: string
  system_instructions: string
  forbidden_rules: string[]
  qualification_questions: string[]
  ending_rules: string[]
  objection_handling: ObjectionPair[]
  transfer_rules: { enabled?: boolean; phone_number?: string; conditions?: string[] }
  voice_config: { provider?: string; voice_id?: string; model?: string; language?: string; speed?: number }
  llm_model: string | null
  temperature: number
  max_call_seconds: number
  silence_prompt_ms: number
  silence_hangup_ms: number
  interruptible: boolean
  ask_language_preference: boolean
  record_calls: boolean
  knowledge_base_id: string | null
  is_active: boolean
  created_at: string
}

export interface PromptPreview {
  system_prompt: string
  greeting: string
  estimated_tokens: number
}

// --- leads ------------------------------------------------------------

export type LeadStatus =
  | 'new' | 'contacted' | 'interested' | 'qualified' | 'not_interested'
  | 'callback' | 'unreachable' | 'do_not_call' | 'converted'

export type InterestLevel = 'unknown' | 'low' | 'medium' | 'high'

export interface Lead {
  id: string
  organization_id: string
  name: string
  phone_number: string
  email: string | null
  company_name: string | null
  status: LeadStatus
  interest_level: InterestLevel
  lead_score: number
  notes: string | null
  call_count: number
  last_called_at: string | null
  follow_up_at: string | null
  created_at: string
}

export interface ImportResult {
  imported: number
  skipped: number
  errors: string[]
}

// --- campaigns --------------------------------------------------------

export type CampaignStatus = 'draft' | 'running' | 'paused' | 'completed' | 'stopped'

export interface Campaign {
  id: string
  organization_id: string
  agent_id: string
  name: string
  status: CampaignStatus
  calling_hours_start: string
  calling_hours_end: string
  timezone: string
  max_concurrent_calls: number
  delay_between_calls_seconds: number
  max_retries: number
  retry_delay_minutes: number
  budget_limit_usd: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface CampaignStats {
  total_leads: number
  pending: number
  completed: number
  failed: number
  calls_made: number
  active_calls: number
  cost_usd: number
  within_calling_hours: boolean
}

export interface CampaignDetail extends Campaign {
  stats: CampaignStats
}

// --- calls ------------------------------------------------------------

export type CallStatus =
  | 'initiated' | 'ringing' | 'in_progress' | 'completed'
  | 'failed' | 'no_answer' | 'busy' | 'canceled'

export interface Call {
  id: string
  agent_id: string
  lead_id: string | null
  campaign_id: string | null
  direction: 'outbound' | 'inbound'
  provider: string
  provider_call_id: string | null
  from_number: string
  to_number: string
  status: CallStatus
  end_reason: string | null
  error: string | null
  started_at: string | null
  answered_at: string | null
  ended_at: string | null
  duration_seconds: number
  summary: string | null
  extracted_data: Record<string, unknown> | null
  recording_url: string | null
  cost_usd: number
  cost_incomplete: boolean
  created_at: string
}

export interface CallTurn {
  turn_index: number
  role: string
  content: string
  state: string | null
  latency_ms: number | null
  barge_in: boolean
  spoken_at: string | null
}

export interface CallUsageLine {
  component: string
  provider: string
  model: string | null
  unit: string
  quantity: number
  cost_usd: number | null
  priced: boolean
}

export interface CallDetail extends Call {
  turns: CallTurn[]
  usage: CallUsageLine[]
}

// --- knowledge --------------------------------------------------------

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  document_count: number
  chunk_count: number
  created_at: string
}

export interface KnowledgeDocument {
  id: string
  knowledge_base_id: string
  title: string
  source_type: string
  mime_type: string
  size_bytes: number
  status: 'pending' | 'processing' | 'ready' | 'failed'
  chunk_count: number
  error: string | null
  created_at: string
}

// --- analytics --------------------------------------------------------

export interface Overview {
  total_calls: number
  calls_today: number
  completed_calls: number
  active_campaigns: number
  total_leads: number
  interested_leads: number
  qualified_leads: number
  average_duration_seconds: number
  total_cost_usd: number
  cost_today_usd: number
  cost_per_call_usd: number
  cost_per_minute_usd: number
  cost_per_qualified_lead_usd: number
  calls_with_incomplete_cost: number
}

export interface AnalyticsBundle {
  overview: Overview
  calls_per_day: { date: string; calls: number; cost_usd: number; completed: number }[]
  outcomes: { status: string; count: number }[]
  lead_funnel: { status: string; count: number }[]
  cost_breakdown: { component: string; cost_usd: number; quantity: number; unpriced_lines: number }[]
  campaigns: {
    campaign_id: string
    name: string
    status: string
    calls: number
    completed: number
    cost_usd: number
    cost_per_call_usd: number
  }[]
  budget: Record<string, number | boolean>
}

// --- settings ---------------------------------------------------------

export interface ProviderStatus {
  selected: string
  configured: boolean
  is_mock: boolean
  available: string[]
}

export interface PlatformSettings {
  organization_name: string
  organization_timezone: string
  daily_budget_usd: number | null
  monthly_budget_usd: number | null
  max_concurrent_calls: number | null
  providers: Record<string, ProviderStatus>
  llm_model: string
  embedding_model: string
  public_base_url: string
  max_global_concurrent_calls: number
  budget: Record<string, number | boolean>
  using_mocks: boolean
}

export interface PricingRate {
  id: string
  component: string
  provider: string
  model: string | null
  unit: string
  rate: number
  currency: string
  region: string | null
  source_url: string
  verified_at: string
  is_active: boolean
}

export interface AgentDraftResponse {
  draft: Partial<Agent>
  notes: string
}

export interface CampaignLeadRow {
  id: string
  lead_id: string
  status: 'pending' | 'dialing' | 'completed' | 'failed' | 'exhausted' | 'skipped'
  attempts: number
  last_attempt_at: string | null
  next_attempt_at: string | null
}
