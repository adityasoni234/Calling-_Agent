import { create } from "zustand";
import { persist } from "zustand/middleware";

import { api, configureApi } from "@/lib/api";
import type {
  AuthResponse,
  AuthUser,
  SupportSessionBanner,
  SupportSessionResponse,
  TokenPair,
} from "@/types/api";

/**
 * Tokens live in localStorage so a refresh doesn't log the user out. That trades
 * XSS exposure for usability; the mitigations are short-lived access tokens,
 * rotating refresh tokens with server-side reuse detection, and no third-party
 * scripts on this origin. Move to httpOnly cookies if the threat model tightens.
 */
interface AuthState {
  user: AuthUser | null;
  tokens: TokenPair | null;
  /**
   * Set only while platform staff are inside this account. Persisted with
   * the tokens so a refresh does not drop the banner and leave a support
   * session looking like an ordinary one.
   */
  supportSession: SupportSessionBanner | null;
  hydrated: boolean;
  setHydrated: () => void;
  setSession: (session: AuthResponse) => void;
  setTokens: (tokens: TokenPair) => void;
  setUser: (user: AuthUser) => void;
  clear: () => void;
  enterSupportSession: (code: string) => Promise<void>;
  endSupportSession: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      tokens: null,
      supportSession: null,
      hydrated: false,

      setHydrated: () => set({ hydrated: true }),
      setSession: (session) =>
        set({ user: session.user, tokens: session.tokens }),
      setTokens: (tokens) => set({ tokens }),
      setUser: (user) => set({ user }),
      clear: () => set({ user: null, tokens: null, supportSession: null }),

      enterSupportSession: async (code) => {
        const session = await api.post<SupportSessionResponse>(
          "/auth/impersonation/exchange",
          { code },
          { auth: false },
        );
        set({
          user: session.user,
          // No refresh token, deliberately: the session must end on its own
          // clock rather than renew itself behind whoever opened it. The
          // empty string keeps the shape the api layer expects; it will
          // never be sent, because a refresh attempt has nothing to send.
          tokens: {
            access_token: session.access_token,
            refresh_token: "",
            token_type: session.token_type,
            expires_in: session.expires_in,
          },
          supportSession: session.session,
        });
      },

      endSupportSession: async () => {
        // Best effort, then clear regardless: staff must never be stuck
        // inside someone else's account because a request failed.
        await api.post("/auth/impersonation/end", {}).catch(() => {});
        set({ user: null, tokens: null, supportSession: null });
        window.location.replace("/login");
      },

      login: async (email, password) => {
        const session = await api.post<AuthResponse>(
          "/auth/login",
          { email, password },
          { auth: false },
        );
        set({ user: session.user, tokens: session.tokens });
      },

      register: async (input) => {
        const session = await api.post<AuthResponse>("/auth/register", input, {
          auth: false,
        });
        set({ user: session.user, tokens: session.tokens });
      },

      logout: async () => {
        const refreshToken = get().tokens?.refresh_token;
        set({ user: null, tokens: null });
        if (refreshToken) {
          // Best effort: the local session is already gone either way.
          await api
            .post(
              "/auth/logout",
              { refresh_token: refreshToken },
              { auth: false },
            )
            .catch(() => {});
        }
      },
    }),
    {
      name: "aca.auth",
      partialize: (state) => ({
        user: state.user,
        tokens: state.tokens,
        supportSession: state.supportSession,
      }),
      // Until localStorage has been read we don't know whether there is a
      // session, and the router must not redirect to /login yet.
      onRehydrateStorage: () => (state) => state?.setHydrated(),
    },
  ),
);

configureApi({
  getAccessToken: () => useAuthStore.getState().tokens?.access_token ?? null,
  getRefreshToken: () => useAuthStore.getState().tokens?.refresh_token ?? null,
  onRefreshed: (tokens) => useAuthStore.getState().setTokens(tokens),
  onSessionLost: () => useAuthStore.getState().clear(),
});

export const selectIsAuthenticated = (state: AuthState) =>
  Boolean(state.tokens?.access_token);
