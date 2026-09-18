import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import type {
  Agent,
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
  KnowledgeBase,
  LeadList,
  KnowledgeDocument,
  Lead,
  Page,
  PlatformSettings,
  PricingRate,
  PromptPreview,
} from '@/types/api'

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

/** Uploads bypass the JSON client: FormData must set its own boundary header. */
async function upload<T>(path: string, file: File, token: string | null): Promise<T> {
  const body = new FormData()
  body.append('file', file)
  const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'
  const response = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => null)
    throw new Error(problem?.error?.message ?? 'Upload failed')
  }
  return response.json() as Promise<T>
}

// --- agents -----------------------------------------------------------

export function useAgents(page = 1) {
  return useQuery({
    queryKey: ['agents', page],
    queryFn: () => api.get<Page<Agent>>(`/agents${query({ page, page_size: 50 })}`),
  })
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: ['agents', id],
    queryFn: () => api.get<Agent>(`/agents/${id}`),
    enabled: Boolean(id),
  })
}

export function useAgentPrompt(id: string | undefined) {
  return useQuery({
    queryKey: ['agents', id, 'prompt'],
    queryFn: () => api.get<PromptPreview>(`/agents/${id}/prompt`),
    enabled: Boolean(id),
  })
}

export function useGenerateAgent() {
  return useMutation({
    mutationFn: (body: { brief: string; company_name?: string; language?: string }) =>
      api.post<AgentDraftResponse>('/agents/generate', body),
  })
}

export function useSaveAgent(id?: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<Agent>) =>
      id ? api.patch<Agent>(`/agents/${id}`, body) : api.post<Agent>('/agents', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['agents'] }),
  })
}

export function useDeleteAgent() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/agents/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['agents'] }),
  })
}

// --- leads ------------------------------------------------------------

export interface LeadQuery {
  page: number
  search?: string
  status?: string
  /** Comma-separated, for views spanning several statuses ("qualified,converted"). */
  statuses?: string
  min_score?: number
  sort?: 'recent' | 'score' | 'name' | 'last_called'
  /** Restrict to one uploaded sheet. */
  list_id?: string
  page_size?: number
}

export function useLeads(params: LeadQuery) {
  return useQuery({
    queryKey: ['leads', params],
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
  })
}

/** Just the total for a segment — one row fetched, so tab counts stay cheap. */
export function useLeadCount(statuses: string) {
  return useQuery({
    queryKey: ['leads', 'count', statuses],
    queryFn: async () =>
      (await api.get<Page<Lead>>(`/leads${query({ page: 1, page_size: 1, statuses })}`)).total,
  })
}

/** The tabs above the leads table: one per uploaded sheet. */
export function useLeadLists() {
  return useQuery({
    queryKey: ['lead-lists'],
    queryFn: () => api.get<LeadList[]>('/leads/lists'),
  })
}

export function useRenameLeadList() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api.patch<LeadList>(`/leads/lists/${id}`, { name }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['lead-lists'] }),
  })
}

export function useDeleteLeadList() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/leads/lists/${id}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['lead-lists'] })
      client.invalidateQueries({ queryKey: ['leads'] })
    },
  })
}

export function useCreateLead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<Lead>) => api.post<Lead>('/leads', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['leads'] }),
  })
}

export function useDeleteLead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/leads/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['leads'] }),
  })
}

export function useImportLeads(token: string | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => upload<ImportResult>('/leads/import', file, token),
    onSuccess: () => client.invalidateQueries({ queryKey: ['leads'] }),
  })
}

// --- campaigns --------------------------------------------------------

export function useCampaigns(page = 1) {
  return useQuery({
    queryKey: ['campaigns', page],
    queryFn: () => api.get<Page<Campaign>>(`/campaigns${query({ page, page_size: 50 })}`),
  })
}

export function useCampaign(id: string | undefined) {
  return useQuery({
    queryKey: ['campaigns', id],
    queryFn: () => api.get<CampaignDetail>(`/campaigns/${id}`),
    enabled: Boolean(id),
    // A running campaign changes on its own; keep the stats close to live.
    refetchInterval: (queryResult) =>
      queryResult.state.data?.status === 'running' ? 5000 : false,
  })
}

export function useCampaignLeads(id: string | undefined, page = 1) {
  return useQuery({
    queryKey: ['campaigns', id, 'leads', page],
    queryFn: () => api.get<Page<CampaignLeadRow>>(`/campaigns/${id}/leads?page=${page}&page_size=25`),
    enabled: Boolean(id),
  })
}

export function useLead(id: string | null | undefined) {
  return useQuery({
    queryKey: ['leads', id],
    queryFn: () => api.get<Lead>(`/leads/${id}`),
    enabled: Boolean(id),
  })
}

export function useCreateCampaign() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<CampaignDetail>('/campaigns', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns'] }),
  })
}

export function useCampaignControl(id: string) {
  const client = useQueryClient()
  return useMutation({
    // "Dial now" is a person asking for a call this second, so it overrides the
    // calling window and retry backoff. Budget and concurrency caps still hold.
    mutationFn: (action: 'start' | 'pause' | 'stop' | 'dispatch') =>
      api.post<DispatchResult>(
        `/campaigns/${id}/${action}${action === 'dispatch' ? '?force=true' : ''}`,
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['campaigns'] })
      client.invalidateQueries({ queryKey: ['calls'] })
    },
  })
}

/** Upload a CSV straight onto a campaign: import and enrol in one step. */
export function useImportCampaignLeads(id: string, token: string | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) =>
      upload<CampaignImportResult>(`/campaigns/${id}/leads/import`, file, token),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['campaigns'] })
      client.invalidateQueries({ queryKey: ['leads'] })
    },
  })
}

export function useAddCampaignLeads(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (leadIds: string[]) => api.post(`/campaigns/${id}/leads`, { lead_ids: leadIds }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['campaigns', id] }),
  })
}

// --- calls ------------------------------------------------------------

export function useCalls(params: { page: number; status?: string; campaign_id?: string }) {
  return useQuery({
    queryKey: ['calls', params],
    queryFn: () =>
      api.get<Page<Call>>(
        `/calls${query({ page: params.page, page_size: 25, status: params.status, campaign_id: params.campaign_id })}`,
      ),
    placeholderData: (previous) => previous,
    refetchInterval: 10_000,
  })
}

export function useCall(id: string | undefined) {
  return useQuery({
    queryKey: ['calls', id],
    queryFn: () => api.get<CallDetail>(`/calls/${id}`),
    enabled: Boolean(id),
  })
}

export function usePlaceCall() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { agent_id: string; lead_id?: string; to_number?: string }) =>
      api.post<Call>('/calls', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['calls'] }),
  })
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
    queryKey: ['calls', callId, 'recording'],
    queryFn: async () => {
      const base = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'
      const token = useAuthStore.getState().tokens?.access_token
      const response = await fetch(`${base}/calls/${callId}/recording`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!response.ok) throw new Error('Recording is not available yet')
      return URL.createObjectURL(await response.blob())
    },
    enabled,
    staleTime: Infinity,
    retry: false,
  })
}

export function useReprocessCall(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post(`/calls/${id}/reprocess`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['calls', id] }),
  })
}

// --- knowledge --------------------------------------------------------

export function useKnowledgeBases() {
  return useQuery({
    queryKey: ['knowledge'],
    queryFn: () => api.get<KnowledgeBase[]>('/knowledge'),
  })
}

export function useDocuments(kbId: string | undefined) {
  return useQuery({
    queryKey: ['knowledge', kbId, 'documents'],
    queryFn: () => api.get<KnowledgeDocument[]>(`/knowledge/${kbId}/documents`),
    enabled: Boolean(kbId),
    refetchInterval: (queryResult) =>
      queryResult.state.data?.some((doc) => doc.status === 'pending' || doc.status === 'processing')
        ? 3000
        : false,
  })
}

export function useCreateKnowledgeBase() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      api.post<KnowledgeBase>('/knowledge', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useUploadDocument(kbId: string, token: string | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) =>
      upload<KnowledgeDocument>(`/knowledge/${kbId}/documents`, file, token),
    onSuccess: () => client.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useAddFaq(kbId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { question: string; answer: string }) =>
      api.post<KnowledgeDocument>(`/knowledge/${kbId}/faqs`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useSearchKnowledge(kbId: string) {
  return useMutation({
    mutationFn: (queryText: string) =>
      api.post<{ hits: { content: string }[] }>(`/knowledge/${kbId}/search`, {
        query: queryText,
        top_k: 5,
      }),
  })
}

export function useDeleteDocument() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/knowledge/documents/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

// --- analytics and settings -------------------------------------------

export function useAnalytics(days = 14) {
  return useQuery({
    queryKey: ['analytics', days],
    queryFn: () => api.get<AnalyticsBundle>(`/analytics${query({ days })}`),
    refetchInterval: 30_000,
  })
}

export function usePlatformSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<PlatformSettings>('/settings'),
  })
}

export function useUpdateOrganization() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      daily_budget_usd?: number | null
      monthly_budget_usd?: number | null
      max_concurrent_calls?: number | null
    }) => api.patch('/settings/organization', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function usePricingRates() {
  return useQuery({
    queryKey: ['settings', 'pricing'],
    queryFn: () => api.get<PricingRate[]>('/settings/pricing'),
  })
}

export function useRepriceCalls() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api.post<{ lines_priced: number; calls_updated: number; cost_added_usd: number }>(
        '/settings/pricing/reprice',
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['calls'] })
      client.invalidateQueries({ queryKey: ['analytics'] })
    },
  })
}

export function useCreatePricingRate() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Omit<PricingRate, 'id' | 'is_active'>) =>
      api.post<PricingRate>('/settings/pricing', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['settings', 'pricing'] }),
  })
}
