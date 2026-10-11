import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { HealthResponse } from "@/types/api";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthResponse>("/health", { auth: false }),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
