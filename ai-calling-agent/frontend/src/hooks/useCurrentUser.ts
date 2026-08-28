import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { selectIsAuthenticated, useAuthStore } from '@/stores/auth'
import type { UserWithOrganization } from '@/types/api'

/**
 * The persisted user is shown immediately; this revalidates it against the API
 * so a disabled account or a renamed organization is reflected on next load.
 */
export function useCurrentUser() {
  const isAuthenticated = useAuthStore(selectIsAuthenticated)
  const setUser = useAuthStore((state) => state.setUser)

  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      const user = await api.get<UserWithOrganization>('/auth/me')
      setUser(user)
      return user
    },
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
  })
}
