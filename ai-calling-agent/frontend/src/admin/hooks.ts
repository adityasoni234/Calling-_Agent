/**
 * Platform-admin data access.
 *
 * Kept out of the shared hooks module so none of it is bundled into the
 * customer application -- the whole reason the admin panel is a separate build.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  AdminOrder,
  ProviderConnection,
  ProviderHealth,
  AdminPackage,
  AdminPackageWrite,
  CreditEntry,
  CustomerProfile,
  OrganizationSummary,
  PlatformEvent,
  PlatformOverview,
  PlatformUser,
} from "@/types/api";

export function usePlatformOverview(enabled = true) {
  return useQuery({
    queryKey: ["platform", "overview"],
    queryFn: () => api.get<PlatformOverview>("/platform/overview"),
    enabled,
    retry: false,
  });
}

export function usePlatformOrganizations(enabled = true) {
  return useQuery({
    queryKey: ["platform", "organizations"],
    queryFn: () => api.get<OrganizationSummary[]>("/platform/organizations"),
    enabled,
    retry: false,
  });
}

export function usePlatformUsers(organizationId?: string) {
  return useQuery({
    queryKey: ["platform", "users", organizationId],
    queryFn: () =>
      api.get<PlatformUser[]>(
        `/platform/users${organizationId ? `?organization_id=${organizationId}` : ""}`,
      ),
    retry: false,
  });
}

export function usePlatformEvents() {
  return useQuery({
    queryKey: ["platform", "events"],
    queryFn: () => api.get<PlatformEvent[]>("/platform/events"),
    retry: false,
  });
}

export function useCreditHistory(organizationId: string | null) {
  return useQuery({
    queryKey: ["platform", "credits", organizationId],
    queryFn: () =>
      api.get<CreditEntry[]>(
        `/platform/organizations/${organizationId}/credits`,
      ),
    enabled: Boolean(organizationId),
  });
}

function platformAction<TBody>(path: (id: string) => string) {
  return function useAction() {
    const client = useQueryClient();
    return useMutation({
      mutationFn: ({ id, body }: { id: string; body?: TBody }) =>
        api.post<{ message: string }>(path(id), body ?? {}),
      onSuccess: () => client.invalidateQueries({ queryKey: ["platform"] }),
    });
  };
}

export const useGrantCredits = platformAction<{
  credits: number;
  note: string;
}>((id) => `/platform/organizations/${id}/credits`);
export const useDeductCredits = platformAction<{
  credits: number;
  note: string;
}>((id) => `/platform/organizations/${id}/credits/deduct`);
export const useSuspendOrganization = platformAction<{ reason: string }>(
  (id) => `/platform/organizations/${id}/suspend`,
);
export const useUnsuspendOrganization = platformAction<never>(
  (id) => `/platform/organizations/${id}/unsuspend`,
);
export const useDeactivateUser = platformAction<never>(
  (id) => `/platform/users/${id}/deactivate`,
);
export const useActivateUser = platformAction<never>(
  (id) => `/platform/users/${id}/activate`,
);

// --- the 360 view -----------------------------------------------------

export function useCustomerProfile(organizationId: string | null) {
  return useQuery({
    queryKey: ["platform", "profile", organizationId],
    queryFn: () =>
      api.get<CustomerProfile>(
        `/platform/organizations/${organizationId}/profile`,
      ),
    enabled: Boolean(organizationId),
    retry: false,
  });
}

// --- packages ---------------------------------------------------------

export function useAdminPackages() {
  return useQuery({
    queryKey: ["platform", "packages"],
    queryFn: () => api.get<AdminPackage[]>("/platform/packages"),
    retry: false,
  });
}

export function useCreatePackage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AdminPackageWrite) =>
      api.post<AdminPackage>("/platform/packages", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["platform"] }),
  });
}

export function useUpdatePackage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdminPackageWrite }) =>
      api.patch<AdminPackage>(`/platform/packages/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["platform"] }),
  });
}

/** Retire, not delete: a package with paid orders is part of the record. */
export function useRetirePackage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete<{ message: string }>(`/platform/packages/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["platform"] }),
  });
}

// --- orders -----------------------------------------------------------

export function useAdminOrders(status?: string) {
  return useQuery({
    queryKey: ["platform", "orders", status ?? "all"],
    queryFn: () =>
      api.get<AdminOrder[]>(
        `/platform/orders${status ? `?status=${status}` : ""}`,
      ),
    retry: false,
  });
}

/**
 * Paid orders whose credits never landed.
 *
 * This should always be empty. Its own query because it is the one number on
 * the platform that means a customer paid us and got nothing.
 */
export function useUnallocatedOrders() {
  return useQuery({
    queryKey: ["platform", "orders", "unallocated"],
    queryFn: () => api.get<AdminOrder[]>("/platform/orders/unallocated"),
    retry: false,
  });
}

export function useRetryAllocation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<AdminOrder>(`/platform/orders/${id}/retry-allocation`, {}),
    onSuccess: () => client.invalidateQueries({ queryKey: ["platform"] }),
  });
}

// --- providers --------------------------------------------------------

export function useProviders() {
  return useQuery({
    queryKey: ["platform", "providers"],
    queryFn: () => api.get<ProviderConnection[]>("/platform/providers"),
    retry: false,
  });
}

export function useSaveProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      slug: string;
      secrets: Record<string, string>;
      config?: Record<string, unknown>;
      is_enabled?: boolean;
    }) => api.put<ProviderConnection>("/platform/providers", body),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["platform", "providers"] }),
  });
}

export function useCheckProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<ProviderHealth>(`/platform/providers/${id}/check`, {}),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["platform", "providers"] }),
  });
}

export function useToggleProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.post<ProviderConnection>(
        `/platform/providers/${id}/toggle?enabled=${enabled}`,
        {},
      ),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["platform", "providers"] }),
  });
}
