import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";
import type {
  Agent,
  Channel,
  Conversation,
  Message as SmsMessage,
  MessageCampaign,
  MessageTemplate,
  MessagingReadiness,
  SendEstimate,
  Suppression,
  Checkout,
  CreditBalance,
  CreditPackage,
  LedgerEntry,
  Order,
  UsageBundle,
  AgentDraftResponse,
  AnalyticsBundle,
  Call,
  CallDetail,
  Campaign,
  CampaignDetail,
  CampaignImportResult,
  CampaignLeadRow,
  DispatchResult,
  ImportResult,
  ApiKey,
  ApiKeyCreated,
  KnowledgeBase,
  LearningSummary,
  LeadList,
  KnowledgeDocument,
  Lead,
  Page,
  PlatformSettings,
  PricingRate,
  PromptPreview,
  Variant,
  WebhookEndpoint,
  WebhookEndpointCreated,
} from "@/types/api";

function query(
  params: Record<string, string | number | undefined | null>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/** Uploads bypass the JSON client: FormData must set its own boundary header. */
async function upload<T>(
  path: string,
  file: File,
  token: string | null,
): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const base =
    import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    throw new Error(problem?.error?.message ?? "Upload failed");
  }
  return response.json() as Promise<T>;
}

// --- agents -----------------------------------------------------------

export function useAgents(page = 1) {
  return useQuery({
    queryKey: ["agents", page],
    queryFn: () =>
      api.get<Page<Agent>>(`/agents${query({ page, page_size: 50 })}`),
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: ["agents", id],
    queryFn: () => api.get<Agent>(`/agents/${id}`),
    enabled: Boolean(id),
  });
}

export function useAgentPrompt(id: string | undefined) {
  return useQuery({
    queryKey: ["agents", id, "prompt"],
    queryFn: () => api.get<PromptPreview>(`/agents/${id}/prompt`),
    enabled: Boolean(id),
  });
}

export function useGenerateAgent() {
  return useMutation({
    mutationFn: (body: {
      brief: string;
      company_name?: string;
      language?: string;
    }) => api.post<AgentDraftResponse>("/agents/generate", body),
  });
}

export function useSaveAgent(id?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Agent>) =>
      id
        ? api.patch<Agent>(`/agents/${id}`, body)
        : api.post<Agent>("/agents", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export function useDeleteAgent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/agents/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["agents"] }),
  });
}

// --- leads ------------------------------------------------------------

export interface LeadQuery {
  page: number;
  search?: string;
  status?: string;
  /** Comma-separated, for views spanning several statuses ("qualified,converted"). */
  statuses?: string;
  min_score?: number;
  sort?: "recent" | "score" | "name" | "last_called";
  /** Restrict to one uploaded sheet. */
  list_id?: string;
  page_size?: number;
}

export function useLeads(params: LeadQuery) {
  return useQuery({
    queryKey: ["leads", params],
    queryFn: () =>
      api.get<Page<Lead>>(
        `/leads${query({
          page: params.page,
          page_size: params.page_size ?? 25,
          search: params.search,
          status: params.status,
          statuses: params.statuses,
          min_score: params.min_score,
          sort: params.sort,
          list_id: params.list_id,
        })}`,
      ),
    placeholderData: (previous) => previous,
  });
}

/** Just the total for a segment — one row fetched, so tab counts stay cheap. */
export function useLeadCount(statuses: string) {
  return useQuery({
    queryKey: ["leads", "count", statuses],
    queryFn: async () =>
      (
        await api.get<Page<Lead>>(
          `/leads${query({ page: 1, page_size: 1, statuses })}`,
        )
      ).total,
  });
}

/** The tabs above the leads table: one per uploaded sheet. */
export function useLeadLists() {
  return useQuery({
    queryKey: ["lead-lists"],
    queryFn: () => api.get<LeadList[]>("/leads/lists"),
  });
}

export function useRenameLeadList() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api.patch<LeadList>(`/leads/lists/${id}`, { name }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["lead-lists"] }),
  });
}

export function useDeleteLeadList() {
  const client = useQueryClient();
  return useMutation({
    // deleteLeads is what the "Delete sheet" button sends; the API defaults to
    // false so nothing else can destroy contacts by accident.
    mutationFn: ({ id, deleteLeads }: { id: string; deleteLeads: boolean }) =>
      api.delete<{ message: string }>(
        `/leads/lists/${id}${deleteLeads ? "?delete_leads=true" : ""}`,
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["lead-lists"] });
      client.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}

export function useCreateLead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Lead>) => api.post<Lead>("/leads", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["leads"] }),
  });
}

export function useDeleteLead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/leads/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["leads"] }),
  });
}

export function useImportLeads(token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      upload<ImportResult>("/leads/import", file, token),
    onSuccess: () => client.invalidateQueries({ queryKey: ["leads"] }),
  });
}

// --- campaigns --------------------------------------------------------

export function useCampaigns(page = 1) {
  return useQuery({
    queryKey: ["campaigns", page],
    queryFn: () =>
      api.get<Page<Campaign>>(`/campaigns${query({ page, page_size: 50 })}`),
  });
}

export function useCampaign(id: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", id],
    queryFn: () => api.get<CampaignDetail>(`/campaigns/${id}`),
    enabled: Boolean(id),
    // A running campaign changes on its own; keep the stats close to live.
    refetchInterval: (queryResult) =>
      queryResult.state.data?.status === "running" ? 5000 : false,
  });
}

export function useCampaignLeads(id: string | undefined, page = 1) {
  return useQuery({
    queryKey: ["campaigns", id, "leads", page],
    queryFn: () =>
      api.get<Page<CampaignLeadRow>>(
        `/campaigns/${id}/leads?page=${page}&page_size=25`,
      ),
    enabled: Boolean(id),
  });
}

export function useLead(id: string | null | undefined) {
  return useQuery({
    queryKey: ["leads", id],
    queryFn: () => api.get<Lead>(`/leads/${id}`),
    enabled: Boolean(id),
  });
}

export function useCreateCampaign() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<CampaignDetail>("/campaigns", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

export function useCampaignControl(id: string) {
  const client = useQueryClient();
  return useMutation({
    // "Dial now" is a person asking for a call this second, so it overrides the
    // calling window and retry backoff. Budget and concurrency caps still hold.
    mutationFn: (action: "start" | "pause" | "stop" | "dispatch") =>
      api.post<DispatchResult>(
        `/campaigns/${id}/${action}${action === "dispatch" ? "?force=true" : ""}`,
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["campaigns"] });
      client.invalidateQueries({ queryKey: ["calls"] });
    },
  });
}

/** Upload a CSV straight onto a campaign: import and enrol in one step. */
/** Put every lead on an uploaded sheet onto this campaign. */
export function useAddSheetToCampaign(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (leadListId: string) =>
      api.post<{ message: string }>(`/campaigns/${id}/leads/from-sheet`, {
        lead_list_id: leadListId,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

export function useImportCampaignLeads(id: string, token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      upload<CampaignImportResult>(
        `/campaigns/${id}/leads/import`,
        file,
        token,
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["campaigns"] });
      client.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}

export function useAddCampaignLeads(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (leadIds: string[]) =>
      api.post(`/campaigns/${id}/leads`, { lead_ids: leadIds }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["campaigns", id] }),
  });
}

// --- calls ------------------------------------------------------------

export function useCalls(params: {
  page: number;
  status?: string;
  campaign_id?: string;
  /** 'human' for manually-dialled calls, 'agent' for the AI's. */
  mode?: "agent" | "human";
}) {
  return useQuery({
    queryKey: ["calls", params],
    queryFn: () =>
      api.get<Page<Call>>(
        `/calls${query({
          page: params.page,
          page_size: 25,
          status: params.status,
          campaign_id: params.campaign_id,
          mode: params.mode,
        })}`,
      ),
    placeholderData: (previous) => previous,
    refetchInterval: 10_000,
  });
}

export function useCall(id: string | undefined) {
  return useQuery({
    queryKey: ["calls", id],
    queryFn: () => api.get<CallDetail>(`/calls/${id}`),
    enabled: Boolean(id),
  });
}

/** Ring the operator's own phone, then bridge them to the lead. */
export function useBridgeCall() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      operator_number: string;
      lead_id?: string;
      to_number?: string;
    }) => api.post<Call>("/calls/bridge", body),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["calls"] });
      client.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}

export function usePlaceCall() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      agent_id: string;
      lead_id?: string;
      to_number?: string;
    }) => api.post<Call>("/calls", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["calls"] }),
  });
}

/**
 * Fetch a call recording as a blob URL.
 *
 * An `<audio src>` cannot send an Authorization header, and putting the access
 * token in the URL would leak it into history and logs -- so the audio is
 * fetched with the header and handed to the player as an object URL.
 */
export function useRecording(callId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["calls", callId, "recording"],
    queryFn: async () => {
      const base =
        import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
      const token = useAuthStore.getState().tokens?.access_token;
      const response = await fetch(`${base}/calls/${callId}/recording`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error("Recording is not available yet");
      return URL.createObjectURL(await response.blob());
    },
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}

export function useReprocessCall(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/calls/${id}/reprocess`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["calls", id] }),
  });
}

// --- knowledge --------------------------------------------------------

export function useKnowledgeBases() {
  return useQuery({
    queryKey: ["knowledge"],
    queryFn: () => api.get<KnowledgeBase[]>("/knowledge"),
  });
}

export function useDocuments(kbId: string | undefined) {
  return useQuery({
    queryKey: ["knowledge", kbId, "documents"],
    queryFn: () => api.get<KnowledgeDocument[]>(`/knowledge/${kbId}/documents`),
    enabled: Boolean(kbId),
    refetchInterval: (queryResult) =>
      queryResult.state.data?.some(
        (doc) => doc.status === "pending" || doc.status === "processing",
      )
        ? 3000
        : false,
  });
}

export function useCreateKnowledgeBase() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      api.post<KnowledgeBase>("/knowledge", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["knowledge"] }),
  });
}

export function useUploadDocument(kbId: string, token: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      upload<KnowledgeDocument>(`/knowledge/${kbId}/documents`, file, token),
    onSuccess: () => client.invalidateQueries({ queryKey: ["knowledge"] }),
  });
}

export function useAddFaq(kbId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { question: string; answer: string }) =>
      api.post<KnowledgeDocument>(`/knowledge/${kbId}/faqs`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["knowledge"] }),
  });
}

export function useSearchKnowledge(kbId: string) {
  return useMutation({
    mutationFn: (queryText: string) =>
      api.post<{ hits: { content: string }[] }>(`/knowledge/${kbId}/search`, {
        query: queryText,
        top_k: 5,
      }),
  });
}

export function useDeleteDocument() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/knowledge/documents/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["knowledge"] }),
  });
}

// --- analytics and settings -------------------------------------------

export function useAnalytics(days = 14) {
  return useQuery({
    queryKey: ["analytics", days],
    queryFn: () => api.get<AnalyticsBundle>(`/analytics${query({ days })}`),
    refetchInterval: 30_000,
  });
}

export function usePlatformSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<PlatformSettings>("/settings"),
  });
}

export function useUpdateOrganization() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      daily_budget_usd?: number | null;
      monthly_budget_usd?: number | null;
      max_concurrent_calls?: number | null;
    }) => api.patch("/settings/organization", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function usePricingRates() {
  return useQuery({
    queryKey: ["settings", "pricing"],
    queryFn: () => api.get<PricingRate[]>("/settings/pricing"),
  });
}

export function useRepriceCalls() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{
        lines_priced: number;
        calls_updated: number;
        cost_added_usd: number;
      }>("/settings/pricing/reprice"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["calls"] });
      client.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useCreatePricingRate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Omit<PricingRate, "id" | "is_active">) =>
      api.post<PricingRate>("/settings/pricing", body),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["settings", "pricing"] }),
  });
}

// --- integrations -----------------------------------------------------

export function useApiKeys() {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api.get<ApiKey[]>("/integrations/keys"),
  });
}

export function useCreateApiKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<ApiKeyCreated>("/integrations/keys", { name }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}

export function useRevokeApiKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/integrations/keys/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}

export function useWebhooks() {
  return useQuery({
    queryKey: ["webhooks"],
    queryFn: () => api.get<WebhookEndpoint[]>("/integrations/webhooks"),
  });
}

export function useCreateWebhook() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      url: string;
      events: string[];
      description?: string;
    }) => api.post<WebhookEndpointCreated>("/integrations/webhooks", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}

export function useDeleteWebhook() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/integrations/webhooks/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["webhooks"] }),
  });
}

export function useTestWebhook() {
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ message: string }>(`/integrations/webhooks/${id}/test`, {}),
  });
}

export function useWebhookEvents() {
  return useQuery({
    queryKey: ["webhook-events"],
    queryFn: () => api.get<string[]>("/integrations/events"),
  });
}

// --- learning engine --------------------------------------------------

export function useLearningSummary() {
  return useQuery({
    queryKey: ["learning", "summary"],
    queryFn: () => api.get<LearningSummary[]>("/learning/summary"),
  });
}

export function useVariants(agentId?: string) {
  return useQuery({
    queryKey: ["learning", "variants", agentId],
    queryFn: () =>
      api.get<Variant[]>(
        `/learning/variants${agentId ? `?agent_id=${agentId}` : ""}`,
      ),
  });
}

export function useDecideVariant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      decision,
    }: {
      id: string;
      decision: "approve" | "reject";
    }) => api.post<Variant>(`/learning/variants/${id}/decide`, { decision }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["learning"] }),
  });
}

export function useProposeVariant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      api.post<Variant[]>(`/learning/agents/${agentId}/propose`, {}),
    onSuccess: () => client.invalidateQueries({ queryKey: ["learning"] }),
  });
}

export function useEnableLearning() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      api.post<{ message: string }>(`/learning/agents/${agentId}/enable`, {}),
    onSuccess: () => client.invalidateQueries({ queryKey: ["learning"] }),
  });
}

// --- billing ----------------------------------------------------------

export function usePackages() {
  return useQuery({
    queryKey: ["packages"],
    queryFn: () => api.get<CreditPackage[]>("/billing/packages"),
    // Prices change rarely; re-reading them on every mount is wasted work.
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreditBalance() {
  return useQuery({
    queryKey: ["credit-balance"],
    queryFn: () => api.get<CreditBalance>("/billing/credits/balance"),
    // A call in flight moves the held figure, so this is worth re-reading.
    refetchInterval: 30_000,
  });
}

export function useCreditLedger(page = 1) {
  return useQuery({
    queryKey: ["credit-ledger", page],
    queryFn: () =>
      api.get<Page<LedgerEntry>>(
        `/billing/credits/ledger${query({ page, page_size: 25 })}`,
      ),
  });
}

export function useOrders(page = 1) {
  return useQuery({
    queryKey: ["orders", page],
    queryFn: () =>
      api.get<Page<Order>>(`/billing/orders${query({ page, page_size: 25 })}`),
  });
}

export function useUsage(days = 30) {
  return useQuery({
    queryKey: ["billing-usage", days],
    queryFn: () => api.get<UsageBundle>(`/billing/usage${query({ days })}`),
  });
}

export function useStartCheckout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (packageId: string) =>
      api.post<Checkout>("/billing/orders", { package_id: packageId }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["orders"] });
      client.invalidateQueries({ queryKey: ["credit-balance"] });
    },
  });
}

export function useConfirmCheckout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      orderId,
      payload,
    }: {
      orderId: string;
      payload: Record<string, unknown>;
    }) => api.post<Order>(`/billing/orders/${orderId}/confirm`, { payload }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["orders"] });
      client.invalidateQueries({ queryKey: ["credit-balance"] });
      client.invalidateQueries({ queryKey: ["credit-ledger"] });
    },
  });
}

// --- messaging --------------------------------------------------------

export interface MessageQuery {
  channel?: Channel;
  status?: string;
  direction?: string;
  conversation_id?: string;
  search?: string;
}

export function useConversations(channel?: Channel, unreadOnly = false) {
  return useQuery({
    queryKey: ["conversations", channel ?? "all", unreadOnly],
    queryFn: () =>
      api.get<Page<Conversation>>(
        `/messaging/conversations${query({ channel, unread_only: unreadOnly ? "true" : undefined, page_size: 100 })}`,
      ),
    // An inbox that needs a manual refresh is an inbox people stop trusting.
    refetchInterval: 20_000,
  });
}

export function useMessages(filters: MessageQuery = {}, page = 1) {
  return useQuery({
    queryKey: ["messages", filters, page],
    queryFn: () =>
      api.get<Page<SmsMessage>>(
        `/messaging/messages${query({ ...filters, page, page_size: 50 })}`,
      ),
  });
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ["messaging-unread"],
    queryFn: () => api.get<{ unread: number }>("/messaging/unread"),
    refetchInterval: 30_000,
  });
}

export function useMarkConversationRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<Conversation>(`/messaging/conversations/${id}/read`, {}),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["conversations"] });
      client.invalidateQueries({ queryKey: ["messaging-unread"] });
    },
  });
}

export interface SendPayload {
  to_number: string;
  channel: Channel;
  body?: string;
  template_id?: string;
  from_number?: string;
  idempotency_key?: string;
}

export function useSendMessage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: SendPayload) =>
      api.post<SmsMessage>("/messaging/messages", payload),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["messages"] });
      client.invalidateQueries({ queryKey: ["conversations"] });
      client.invalidateQueries({ queryKey: ["credit-balance"] });
    },
  });
}

/**
 * Price a send before committing to it.
 *
 * A mutation rather than a query: it is an explicit "show me the bill" step,
 * and firing it on every keystroke would both spam the server and make the
 * number flicker while someone is still typing the recipient list.
 */
export function useEstimateSend() {
  return useMutation({
    mutationFn: (payload: {
      channel: Channel;
      recipients: string[];
      body?: string;
      template_id?: string;
    }) => api.post<SendEstimate>("/messaging/estimate", payload),
  });
}

export function useTemplates(channel?: Channel) {
  return useQuery({
    queryKey: ["templates", channel ?? "all"],
    queryFn: () =>
      api.get<MessageTemplate[]>(`/messaging/templates${query({ channel })}`),
  });
}

export function useCreateTemplate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      channel: Channel;
      body: string;
      language?: string;
      category?: string;
    }) => api.post<MessageTemplate>("/messaging/templates", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["templates"] }),
  });
}

export function useDeleteTemplate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/templates/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["templates"] }),
  });
}

export function useSuppressions(page = 1, search?: string) {
  return useQuery({
    queryKey: ["suppressions", page, search],
    queryFn: () =>
      api.get<Page<Suppression>>(
        `/messaging/suppressions${query({ page, search, page_size: 50 })}`,
      ),
  });
}

export function useAddSuppression() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      contact_number: string;
      channel?: Channel;
      reason?: string;
      note?: string;
    }) => api.post<Suppression>("/messaging/suppressions", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["suppressions"] }),
  });
}

export function useRemoveSuppression() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/suppressions/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["suppressions"] }),
  });
}

export function useMessageCampaigns() {
  return useQuery({
    queryKey: ["message-campaigns"],
    queryFn: () => api.get<MessageCampaign[]>("/messaging/campaigns"),
    // A running campaign moves; a list that needs refreshing is one people
    // stop believing.
    refetchInterval: 10_000,
  });
}

export function useCreateMessageCampaign() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      channel: Channel;
      body?: string;
      template_id?: string;
      lead_list_id?: string;
      messages_per_minute?: number;
      scheduled_at?: string;
    }) => api.post<MessageCampaign>("/messaging/campaigns", body),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["message-campaigns"] }),
  });
}

export function useControlMessageCampaign() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post<MessageCampaign>(`/messaging/campaigns/${id}/${action}`, {}),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["message-campaigns"] });
      client.invalidateQueries({ queryKey: ["messages"] });
    },
  });
}

export function useMessagingReadiness() {
  return useQuery({
    queryKey: ["messaging-readiness"],
    queryFn: () => api.get<MessagingReadiness>("/messaging/readiness"),
    staleTime: 60_000,
  });
}

export function useSubmitTemplate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, category }: { id: string; category: string }) =>
      api.post<MessageTemplate>(
        `/messaging/templates/${id}/submit?category=${category}`,
        {},
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["templates"] });
      client.invalidateQueries({ queryKey: ["messaging-readiness"] });
    },
  });
}

export function useSyncTemplates() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<MessageTemplate[]>("/messaging/templates/sync", {}),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["templates"] });
      client.invalidateQueries({ queryKey: ["messaging-readiness"] });
    },
  });
}
