import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  Agent,
  AnalyticsBundle,
  Call,
  CallDetail,
  Campaign,
  CampaignDetail,
  ImportResult,
  KnowledgeBase,
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

export function useLeads(params: { page: number; search?: string; status?: string }) {
  return useQuery({
    queryKey: ['leads', params],
    queryFn: () =>
      api.get<Page<Lead>>(
        `/leads${query({ page: params.page, page_size: 25, search: params.search, status: params.status })}`,
      ),
    placeholderData: (previous) => previous,
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
    mutationFn: (action: 'start' | 'pause' | 'stop' | 'dispatch') =>
      api.post(`/campaigns/${id}/${action}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['campaigns'] })
      client.invalidateQueries({ queryKey: ['calls'] })
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

export function usePricingRates() {
  return useQuery({
    queryKey: ['settings', 'pricing'],
    queryFn: () => api.get<PricingRate[]>('/settings/pricing'),
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
