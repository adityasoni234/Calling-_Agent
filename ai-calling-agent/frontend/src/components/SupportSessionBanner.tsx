import { useEffect, useState } from "react";

import { useAuthStore } from "@/stores/auth";

/**
 * The strip across the top while Stockvala staff are inside this account.
 *
 * It is loud on purpose. A support session that looks like an ordinary one
 * is a session someone will forget they are in, and then act in. Everything
 * here answers a question staff would otherwise have to remember: whose
 * account is this, who am I signed in as, can I change anything, and how
 * long before this closes under me.
 *
 * The countdown is live rather than a timestamp. "Ends at 14:20" has to be
 * subtracted from the clock; "6 minutes left" does not.
 */
export function SupportSessionBannerBar() {
  const banner = useAuthStore((state) => state.supportSession);
  const endSession = useAuthStore((state) => state.endSupportSession);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (!banner) return;
    const tick = () => {
      const ms = new Date(banner.expires_at).getTime() - Date.now();
      setMinutes(ms <= 0 ? 0 : Math.ceil(ms / 60_000));
    };
    tick();
    const timer = window.setInterval(tick, 15_000);
    return () => window.clearInterval(timer);
  }, [banner]);

  if (!banner) return null;

  return (
    <div className="sticky top-0 z-30 border-b border-amber-300 bg-amber-100 px-4 py-2 text-amber-950 sm:px-6">
      {/* On a phone the four pieces cannot share a line: the sentence gets
          squeezed to a word per line and collides with the countdown. So the
          controls take the first row and the sentence takes the second, and
          `order` puts them back on one line from `sm` up. */}
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-2">
        <span className="order-1 inline-flex items-center gap-1.5 rounded-full bg-amber-900 px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-amber-50 sm:order-none">
          Support session
        </span>
        <p className="order-4 w-full text-xs leading-relaxed sm:order-none sm:w-auto sm:min-w-0 sm:flex-1 sm:text-sm">
          You are <strong>{banner.admin_email}</strong>, viewing{" "}
          <strong>{banner.organization_name}</strong> as{" "}
          <strong>{banner.target_email}</strong>.{" "}
          {banner.read_only ? (
            <span className="whitespace-nowrap">Nothing can be changed.</span>
          ) : (
            <span className="whitespace-nowrap font-semibold">
              Changes you make are real.
            </span>
          )}
        </p>
        {minutes !== null && (
          <span className="order-2 ml-auto whitespace-nowrap text-xs tabular-nums sm:order-none sm:ml-0">
            {minutes === 0 ? "Ending now" : `${minutes} min left`}
          </span>
        )}
        <button
          type="button"
          disabled={leaving}
          onClick={() => {
            setLeaving(true);
            void endSession();
          }}
          className="order-3 whitespace-nowrap rounded-lg bg-amber-900 px-3 py-1.5 text-xs font-medium text-amber-50 transition-colors hover:bg-amber-950 disabled:opacity-60 sm:order-none"
        >
          {leaving ? "Leaving…" : "Leave account"}
        </button>
      </div>
    </div>
  );
}

/**
 * The landing point for a handoff link from the admin console.
 *
 * The code arrives in the URL fragment, which never reaches a server, and is
 * wiped from history before anything else runs -- a back button that could
 * replay a session link would undo the single-use rule from the user's side.
 */
export function SupportSessionEntry() {
  const enter = useAuthStore((state) => state.enterSupportSession);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = new URLSearchParams(
      window.location.hash.replace(/^#/, ""),
    ).get("code");
    // Replace rather than push: the fragment is gone from this entry and
    // there is no earlier entry holding it either.
    window.history.replaceState(null, "", "/support-session");

    if (!code) {
      setError("This link is missing its code. Open the session again.");
      return;
    }
    enter(code)
      .then(() => {
        window.location.replace("/dashboard");
      })
      .catch((err: unknown) =>
        setError(
          err instanceof Error
            ? err.message
            : "This link is no longer valid. Open the session again.",
        ),
      );
    // Runs once: the code is single-use, so a re-run would spend a code that
    // has already been spent and report a failure that did not happen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-50 px-6">
      <div className="w-full max-w-md text-center">
        {error ? (
          <>
            <h1 className="font-display text-2xl text-ink-900">
              Could not open the session
            </h1>
            <p className="mt-3 text-sm leading-relaxed text-ink-600">{error}</p>
            <p className="mt-6 text-xs text-ink-400">
              Handoff links are good for sixty seconds and can only be used
              once.
            </p>
          </>
        ) : (
          <>
            <h1 className="font-display text-2xl text-ink-900">
              Opening the account…
            </h1>
            <p className="mt-3 text-sm text-ink-500">One moment.</p>
          </>
        )}
      </div>
    </div>
  );
}
