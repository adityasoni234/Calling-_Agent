import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { api, configureApi } from '@/lib/api'
import type { AuthResponse, TokenPair, User } from '@/types/api'

/**
 * Tokens live in localStorage so a refresh doesn't log the user out. That trades
 * XSS exposure for usability; the mitigations are short-lived access tokens,
 * rotating refresh tokens with server-side reuse detection, and no third-party
 * scripts on this origin. Move to httpOnly cookies if the threat model tightens.
 */
interface AuthState {
  user: User | null
  tokens: TokenPair | null
  hydrated: boolean
  setHydrated: () => void
  setSession: (session: AuthResponse) => void
  setTokens: (tokens: TokenPair) => void
  setUser: (user: User) => void
  clear: () => void
  login: (email: string, password: string) => Promise<void>
  register: (input: {
    email: string
    password: string
    full_name: string
    organization_name: string
  }) => Promise<void>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      tokens: null,
      hydrated: false,

      setHydrated: () => set({ hydrated: true }),
      setSession: (session) => set({ user: session.user, tokens: session.tokens }),
      setTokens: (tokens) => set({ tokens }),
      setUser: (user) => set({ user }),
      clear: () => set({ user: null, tokens: null }),

      login: async (email, password) => {
        const session = await api.post<AuthResponse>('/auth/login', { email, password }, { auth: false })
        set({ user: session.user, tokens: session.tokens })
      },

      register: async (input) => {
        const session = await api.post<AuthResponse>('/auth/register', input, { auth: false })
        set({ user: session.user, tokens: session.tokens })
      },

      logout: async () => {
        const refreshToken = get().tokens?.refresh_token
        set({ user: null, tokens: null })
        if (refreshToken) {
          // Best effort: the local session is already gone either way.
          await api.post('/auth/logout', { refresh_token: refreshToken }, { auth: false }).catch(() => {})
        }
      },
    }),
    {
      name: 'aca.auth',
      partialize: (state) => ({ user: state.user, tokens: state.tokens }),
      // Until localStorage has been read we don't know whether there is a
      // session, and the router must not redirect to /login yet.
      onRehydrateStorage: () => (state) => state?.setHydrated(),
    },
  ),
)

configureApi({
  getAccessToken: () => useAuthStore.getState().tokens?.access_token ?? null,
  getRefreshToken: () => useAuthStore.getState().tokens?.refresh_token ?? null,
  onRefreshed: (tokens) => useAuthStore.getState().setTokens(tokens),
  onSessionLost: () => useAuthStore.getState().clear(),
})

export const selectIsAuthenticated = (state: AuthState) => Boolean(state.tokens?.access_token)
