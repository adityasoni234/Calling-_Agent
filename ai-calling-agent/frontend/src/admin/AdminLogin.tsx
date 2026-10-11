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
    <div className="grid min-h-screen place-items-center bg-slate-950 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-slate-100 text-xs font-bold text-slate-950">
              SV
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-slate-100">Stockvala</p>
              <p className="text-[0.7rem] uppercase tracking-[0.14em] text-slate-500">
                Platform administration
              </p>
            </div>
          </div>
          <p className="mt-5 text-sm leading-relaxed text-slate-400">
            Internal tool. Signing in here gives you access to every customer
            account on the platform.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/70 p-6"
          noValidate
        >
          {error && (
            <p className="rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          <label className="block">
            <span className="text-xs font-medium text-slate-400">Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:border-slate-500"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-slate-400">Password</span>
            <div className="relative mt-1.5">
              <input
                type={revealed ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 pr-16 text-sm text-slate-100 outline-none transition-colors focus:border-slate-500"
              />
              <button
                type="button"
                onClick={() => setRevealed((shown) => !shown)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-[0.7rem] font-medium text-slate-500 transition-colors hover:text-slate-300"
              >
                {revealed ? "Hide" : "Show"}
              </button>
            </div>
          </label>

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-slate-100 px-4 py-2.5 text-sm font-semibold text-slate-950 transition-colors hover:bg-white disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-[0.7rem] leading-relaxed text-slate-600">
          Not a customer login. Customers sign in at the main dashboard.
        </p>
      </div>
    </div>
  );
}
