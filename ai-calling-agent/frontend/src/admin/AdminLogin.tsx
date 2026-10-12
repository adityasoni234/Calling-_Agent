import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, NetworkError } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

/**
 * The platform sign-in.
 *
 * Deliberately not the customer login: no product branding, no "create your
 * organization" link, and it says plainly what you are signing in to. Someone
 * who lands here by accident should immediately know they are in the wrong
 * place, and staff should know they are about to act on every customer's data.
 */
export function AdminLogin() {
  const login = useAuthStore((state) => state.login);
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof NetworkError
          ? err.message
          : "Could not sign in",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-ink-50 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-700 text-xs font-bold text-white">
              SV
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-ink-900">Stockvala</p>
              <p className="text-[0.7rem] uppercase tracking-[0.14em] text-ink-400">
                Platform administration
              </p>
            </div>
          </div>
          <p className="mt-5 text-sm leading-relaxed text-ink-500">
            Internal tool. Signing in here gives you access to every customer
            account on the platform.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-xl border border-ink-200/60 bg-white/70 p-6"
          noValidate
        >
          {error && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          <label className="block">
            <span className="text-xs font-medium text-ink-500">Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-ink-300/70 bg-ink-50 px-3 py-2.5 text-sm text-ink-900 outline-none transition-colors focus:border-brand-600"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink-500">Password</span>
            <div className="relative mt-1.5">
              <input
                type={revealed ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full rounded-lg border border-ink-300/70 bg-ink-50 px-3 py-2.5 pr-16 text-sm text-ink-900 outline-none transition-colors focus:border-brand-600"
              />
              <button
                type="button"
                onClick={() => setRevealed((shown) => !shown)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-[0.7rem] font-medium text-ink-400 transition-colors hover:text-ink-700"
              >
                {revealed ? "Hide" : "Show"}
              </button>
            </div>
          </label>

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-brand-700 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-ink-50 disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-[0.7rem] leading-relaxed text-ink-400">
          Not a customer login. Customers sign in at the main dashboard.
        </p>
      </div>
    </div>
  );
}
