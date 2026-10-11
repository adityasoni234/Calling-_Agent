import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { selectIsAuthenticated, useAuthStore } from "@/stores/auth";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const hydrated = useAuthStore((state) => state.hydrated);
  const location = useLocation();

  // Redirecting before localStorage has been read would bounce a logged-in
  // user to /login on every hard refresh.
  if (!hydrated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-ink-300 border-t-brand-600" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
