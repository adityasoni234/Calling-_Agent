export type UserRole = "owner" | "admin" | "operator" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  is_active: boolean;
  created_at: string;
}

export interface User {
  id: string;
  organization_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  /** Platform staff, not a customer. Gates the admin surface. */
  is_platform_admin: boolean;
}

export interface UserWithOrganization extends User {
  organization: Organization;
}

/** Login returns a bare user; /auth/me enriches it with the organization. */
export type AuthUser = User & { organization?: Organization };

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthResponse {
  user: User;
  tokens: TokenPair;
}

export interface MessageResponse {
  message: string;
}

export interface HealthResponse {
  status: string;
  app: string;
  environment: string;
  version: string;
  database: string;
}

/** Every error the API returns has this shape -- see backend `app/core/errors.py`. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: { field: string; message: string; type: string }[] | unknown;
  };
}

// --- pagination -------------------------------------------------------

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// --- agents -----------------------------------------------------------

export type AgentLanguage = "en" | "hi" | "hinglish" | "auto";

export interface ObjectionPair {
  objection: string;
  response: string;
}

export interface Agent {
  id: string;
  organization_id: string;
  name: string;
  role_title: string;
  company_name: string;
  personality: string;
  primary_objective: string;
  secondary_objectives: string[];
  language: AgentLanguage;
  greeting: string;
  system_instructions: string;
  forbidden_rules: string[];
  qualification_questions: string[];
  ending_rules: string[];
  objection_handling: ObjectionPair[];
  transfer_rules: {
    enabled?: boolean;
    phone_number?: string;
    conditions?: string[];
  };
  voice_config: {
    provider?: string;
    voice_id?: string;
    model?: string;
    language?: string;
    speed?: number;
  };
  llm_model: string | null;
  temperature: number;
  max_call_seconds: number;
  silence_prompt_ms: number;
  silence_hangup_ms: number;
  interruptible: boolean;
  ask_language_preference: boolean;
  record_calls: boolean;
  knowledge_base_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface PromptPreview {
  system_prompt: string;
  greeting: string;
  estimated_tokens: number;
}

// --- leads ------------------------------------------------------------

export type LeadStatus =
  | "new"
  | "contacted"
  | "interested"
  | "qualified"
  | "not_interested"
  | "callback"
  | "unreachable"
  | "do_not_call"
  | "converted";

export type InterestLevel = "unknown" | "low" | "medium" | "high";

export interface Lead {
  id: string;
  organization_id: string;
  name: string;
  phone_number: string;
  email: string | null;
  company_name: string | null;
  status: LeadStatus;
  interest_level: InterestLevel;
  lead_score: number;
  notes: string | null;
  call_count: number;
  last_called_at: string | null;
  follow_up_at: string | null;
  created_at: string;
}

export interface LeadList {
  id: string;
  name: string;
  source: string;
  source_filename: string | null;
  imported_count: number;
  skipped_count: number;
  /** Live membership count — drifts from imported_count as leads are deleted. */
  lead_count: number;
  created_at: string;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: string[];
  /** The sheet this upload created, when it created one. */
  lead_list: LeadList | null;
}

// --- campaigns --------------------------------------------------------

export interface CampaignImportResult {
  imported: number;
  skipped: number;
  /** How many of the file's people are now on the campaign's call list. */
  attached: number;
  errors: string[];
}

export interface DispatchResult {
  started: number;
  reason: string;
}

export type CampaignStatus =
  "draft" | "running" | "paused" | "completed" | "stopped";

export interface Campaign {
  id: string;
  organization_id: string;
  agent_id: string;
  name: string;
  status: CampaignStatus;
  calling_hours_start: string;
  calling_hours_end: string;
  timezone: string;
  max_concurrent_calls: number;
  delay_between_calls_seconds: number;
  max_retries: number;
  retry_delay_minutes: number;
  budget_limit_usd: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface CampaignStats {
  total_leads: number;
  pending: number;
  completed: number;
  failed: number;
  calls_made: number;
  active_calls: number;
  cost_usd: number;
  within_calling_hours: boolean;
}

export interface CampaignDetail extends Campaign {
  stats: CampaignStats;
}

// --- calls ------------------------------------------------------------

export type CallStatus =
  | "initiated"
  | "ringing"
  | "in_progress"
  | "completed"
  | "failed"
  | "no_answer"
  | "busy"
  | "canceled";

export type CallMode = "agent" | "human";

export interface Call {
  id: string;
  /** Null on a human-operated call — there is no AI agent behind it. */
  agent_id: string | null;
  lead_id: string | null;
  campaign_id: string | null;
  direction: "outbound" | "inbound";
  mode: CallMode;
  operator_number: string | null;
  provider: string;
  provider_call_id: string | null;
  from_number: string;
  to_number: string;
  status: CallStatus;
  end_reason: string | null;
  error: string | null;
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  summary: string | null;
  extracted_data: Record<string, unknown> | null;
  recording_url: string | null;
  cost_usd: number;
  cost_incomplete: boolean;
  created_at: string;
}

export interface CallTurn {
  turn_index: number;
  role: string;
  content: string;
  state: string | null;
  latency_ms: number | null;
  barge_in: boolean;
  spoken_at: string | null;
}

export interface CallUsageLine {
  component: string;
  provider: string;
  model: string | null;
  unit: string;
  quantity: number;
  cost_usd: number | null;
  priced: boolean;
}

export interface CallDetail extends Call {
  turns: CallTurn[];
  usage: CallUsageLine[];
}

// --- knowledge --------------------------------------------------------

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
  created_at: string;
}

export interface KnowledgeDocument {
  id: string;
  knowledge_base_id: string;
  title: string;
  source_type: string;
  mime_type: string;
  size_bytes: number;
  status: "pending" | "processing" | "ready" | "failed";
  chunk_count: number;
  error: string | null;
  created_at: string;
}

// --- analytics --------------------------------------------------------

export interface Overview {
  total_calls: number;
  calls_today: number;
  completed_calls: number;
  active_campaigns: number;
  total_leads: number;
  interested_leads: number;
  qualified_leads: number;
  average_duration_seconds: number;
  total_cost_usd: number;
  cost_today_usd: number;
  cost_per_call_usd: number;
  cost_per_minute_usd: number;
  cost_per_qualified_lead_usd: number;
  calls_with_incomplete_cost: number;
}

export interface AnalyticsBundle {
  overview: Overview;
  calls_per_day: {
    date: string;
    calls: number;
    cost_usd: number;
    completed: number;
  }[];
  outcomes: { status: string; count: number }[];
  lead_funnel: { status: string; count: number }[];
  cost_breakdown: {
    component: string;
    cost_usd: number;
    quantity: number;
    unpriced_lines: number;
  }[];
  campaigns: {
    campaign_id: string;
    name: string;
    status: string;
    calls: number;
    completed: number;
    cost_usd: number;
    cost_per_call_usd: number;
  }[];
  budget: Record<string, number | boolean>;
}

// --- settings ---------------------------------------------------------

export interface ProviderStatus {
  selected: string;
  configured: boolean;
  is_mock: boolean;
  available: string[];
}

export interface PlatformSettings {
  organization_name: string;
  organization_timezone: string;
  daily_budget_usd: number | null;
  monthly_budget_usd: number | null;
  max_concurrent_calls: number | null;
  providers: Record<string, ProviderStatus>;
  llm_model: string;
  embedding_model: string;
  public_base_url: string;
  max_global_concurrent_calls: number;
  budget: Record<string, number | boolean>;
  using_mocks: boolean;
}

export interface PricingRate {
  id: string;
  component: string;
  provider: string;
  model: string | null;
  unit: string;
  rate: number;
  currency: string;
  region: string | null;
  source_url: string;
  verified_at: string;
  is_active: boolean;
}

export interface AgentDraftResponse {
  draft: Partial<Agent>;
  notes: string;
}

export interface CampaignLeadRow {
  id: string;
  lead_id: string;
  status:
    "pending" | "dialing" | "completed" | "failed" | "exhausted" | "skipped";
  attempts: number;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
}

// --- integrations -----------------------------------------------------

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/** Only ever returned by the create call — the plaintext is not stored. */
export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface WebhookEndpoint {
  id: string;
  url: string;
  events: string[];
  description: string | null;
  is_active: boolean;
  failure_count: number;
  last_delivery_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface WebhookEndpointCreated extends WebhookEndpoint {
  secret: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  event: string;
  status: string;
  attempts: number;
  response_code: number | null;
  error: string | null;
  created_at: string;
}

// --- learning engine --------------------------------------------------

export interface Variant {
  id: string;
  agent_id: string;
  kind: "greeting" | "objection" | "style_rule";
  slot: string | null;
  content: string;
  status: "candidate" | "active" | "retired";
  is_baseline: boolean;
  trials: number;
  successes: number;
  rationale: string | null;
  retired_reason: string | null;
  last_used_at: string | null;
  created_at: string;
  /** Laplace-smoothed posterior mean — a 1-for-1 arm does not read as 100%. */
  mean_reward: number;
}

export interface LearningSummary {
  agent_id: string;
  agent_name: string;
  active_variants: number;
  candidates: number;
  retired: number;
  scored_calls: number;
  average_reward: number | null;
  best: Variant | null;
  baseline: Variant | null;
}

// --- platform administration ------------------------------------------

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  plan: string;
  is_active: boolean;
  is_suspended: boolean;
  suspended_reason: string | null;
  credit_balance: number;
  credit_overdraft: number;
  created_at: string;
  users: number;
  calls: number;
  calls_30d: number;
  minutes_30d: number;
  provider_cost_usd: number;
  /** Lifetime. Never compare this against the 30-day cost figures. */
  credits_used: number;
  /** Same window as provider_cost_usd, so margin is apples-to-apples. */
  credits_used_30d: number;
  last_call_at: string | null;
}

export interface PlatformOverview {
  organizations: number;
  active_organizations: number;
  suspended: number;
  users: number;
  calls_30d: number;
  minutes_30d: number;
  credits_outstanding: number;
  credits_consumed_30d: number;
  provider_cost_30d_usd: number;
  gross_margin_30d_usd: number;
}

export interface PlatformUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  is_platform_admin: boolean;
  last_login_at: string | null;
  created_at: string;
  organization_id: string;
  organization_name: string;
}

export interface CreditEntry {
  id: string;
  kind: string;
  amount: number;
  balance_after: number;
  call_id: string | null;
  note: string | null;
  provider_cost_usd: number | null;
  created_at: string;
}

export interface PlatformEvent {
  id: string;
  actor_email: string;
  action: string;
  organization_id: string | null;
  target: string | null;
  detail: string | null;
  created_at: string;
}

// --- billing ----------------------------------------------------------

export interface CreditPackage {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  currency: string;
  price_minor: number;
  tax_minor: number;
  payable_minor: number;
  base_credits: number;
  bonus_credits: number;
  total_credits: number;
  validity_days: number | null;
  display_order: number;
}

export interface CreditBalance {
  balance: number;
  /** Set aside for calls currently dialling. */
  held: number;
  /** balance - held. The number that decides whether a call can start. */
  spendable: number;
  overdraft: number;
  plan: string;
  is_suspended: boolean;
  suspended_reason: string | null;
  lifetime_purchased: number;
  lifetime_granted: number;
  lifetime_consumed: number;
  consumed_today: number;
  consumed_this_month: number;
}

export interface Order {
  id: string;
  reference: string;
  status: string;
  package_name: string;
  currency: string;
  price_minor: number;
  tax_minor: number;
  total_minor: number;
  base_credits: number;
  bonus_credits: number;
  total_credits: number;
  provider: string | null;
  provider_order_id: string | null;
  provider_payment_id: string | null;
  paid_at: string | null;
  credits_allocated_at: string | null;
  refunded_minor: number;
  failure_reason: string | null;
  created_at: string;
}

export interface Checkout {
  order: Order;
  /** False when no payment provider is set up. The UI must say so plainly. */
  provider_configured: boolean;
  provider: string;
  checkout: Record<string, unknown> | null;
  message: string | null;
}

export interface LedgerEntry {
  id: string;
  kind: string;
  amount: number;
  balance_after: number;
  call_id: string | null;
  order_id: string | null;
  note: string | null;
  created_at: string;
}

export interface UsageBundle {
  days: number;
  total_credits: number;
  total_calls: number;
  daily: { day: string; credits: number; calls: number }[];
}

// --- platform admin: packages, orders, customer profile ---------------

export interface AdminPackage {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  kind: string;
  price_minor: number;
  currency: string;
  tax_bps: number;
  tax_minor: number;
  payable_minor: number;
  base_credits: number;
  bonus_credits: number;
  total_credits: number;
  validity_days: number | null;
  is_active: boolean;
  is_public: boolean;
  display_order: number;
  max_per_organization: number | null;
  created_at: string;
  /** Paid orders referencing it. A package with sales is retired, never deleted. */
  orders_paid: number;
  revenue_minor: number;
}

export interface AdminPackageWrite {
  name: string;
  slug: string;
  description?: string | null;
  price_minor: number;
  currency?: string;
  tax_bps?: number;
  base_credits: number;
  bonus_credits?: number;
  validity_days?: number | null;
  is_active?: boolean;
  is_public?: boolean;
  display_order?: number;
  max_per_organization?: number | null;
}

export interface AdminOrder {
  id: string;
  reference: string;
  organization_id: string;
  organization_name: string;
  status: string;
  package_name: string;
  currency: string;
  total_minor: number;
  total_credits: number;
  provider: string | null;
  provider_payment_id: string | null;
  paid_at: string | null;
  credits_allocated_at: string | null;
  refunded_minor: number;
  failure_reason: string | null;
  created_at: string;
}

export interface ProfileAgent {
  id: string;
  name: string;
  role_title: string | null;
  is_active: boolean;
  language: string;
  calls: number;
  minutes: number;
  provider_cost_usd: number;
  created_at: string;
  updated_at: string | null;
}

export interface ProfileCall {
  id: string;
  to_number: string;
  status: string;
  source: string;
  source_detail: string | null;
  mode: string;
  initiated_by_user_id: string | null;
  duration_seconds: number | null;
  cost_usd: number | null;
  created_at: string;
}

/** One customer, assembled server-side so every figure is from one moment. */
export interface CustomerProfile {
  organization: OrganizationSummary;
  users: PlatformUser[];
  balance: number;
  held: number;
  spendable: number;
  lifetime_purchased: number;
  lifetime_granted: number;
  lifetime_consumed: number;
  /** Matches provider_cost_30d_usd's window, so margin is apples-to-apples. */
  consumed_30d: number;
  paid_orders: number;
  paid_minor: number;
  refunded_minor: number;
  calls_total: number;
  calls_30d: number;
  minutes_30d: number;
  failed_30d: number;
  by_source: Record<string, number>;
  provider_cost_30d_usd: number;
  agents: ProfileAgent[];
  recent_calls: ProfileCall[];
  recent_credits: CreditEntry[];
  recent_orders: AdminOrder[];
  /** Paid orders whose credits never landed. Should always be empty. */
  unallocated_orders: AdminOrder[];
}

// --- messaging --------------------------------------------------------

export type Channel = "sms" | "whatsapp";

export interface Message {
  id: string;
  conversation_id: string | null;
  campaign_id: string | null;
  channel: Channel;
  direction: "outbound" | "inbound";
  status: string;
  from_number: string;
  to_number: string;
  body: string | null;
  segments: number;
  region: string | null;
  provider: string | null;
  provider_message_id: string | null;
  error_code: string | null;
  error_message: string | null;
  /** A string, not a number: JSON numbers are floats and money is not. */
  customer_charge_usd: string | null;
  provider_cost_usd: string | null;
  cost_incomplete: boolean;
  suppression_reason: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  channel: Channel;
  contact_number: string;
  contact_name: string | null;
  lead_id: string | null;
  last_message_at: string | null;
  last_inbound_at: string | null;
  unread_count: number;
  is_archived: boolean;
  /** Whether a free-form WhatsApp reply is allowed right now. Server-computed. */
  session_open: boolean;
  created_at: string;
}

export interface MessageTemplate {
  id: string;
  channel: Channel;
  name: string;
  language: string;
  category: string | null;
  body: string;
  variables: string[];
  status: string;
  rejection_reason: string | null;
  provider_template_id: string | null;
  placeholder_count: number;
  created_at: string;
}

export interface Suppression {
  id: string;
  contact_number: string;
  channel: Channel | null;
  reason: string;
  note: string | null;
  created_at: string;
}

/** Everything a sender should see before committing to a bulk send. */
export interface SendEstimate {
  recipients: number;
  suppressed: number;
  billable_recipients: number;
  segments_per_message: number;
  total_segments: number;
  customer_charge_usd: string;
  provider_cost_usd: string;
  gross_profit_usd: string | null;
  gross_margin_percent: string | null;
  cost_incomplete: boolean;
  notes: string[];
}
