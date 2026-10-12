import { useState } from "react";

import {
  useEndImpersonation,
  useImpersonationSessions,
  useStartImpersonation,
} from "@/admin/hooks";
import { Action, Empty, Grid, PageTitle, Panel, Pill } from "@/admin/ui";
import type { ImpersonationSession, PlatformUser } from "@/types/api";
import { formatDateTime } from "@/lib/format";

/** Minutes left, or null once it is over. */
function remaining(session: ImpersonationSession): number | null {
  if (!session.is_active) return null;
  const ms = new Date(session.expires_at).getTime() - Date.now();
  return ms <= 0 ? null : Math.ceil(ms / 60_000);
}

/**
 * The dialog that opens a session.
 *
 * Exported because the same decision -- which user, why, and whether it can
 * write -- has to be made from the user list and from a customer's profile,
 * and a second copy of it would be a second place for the reason box to go
 * missing.
 */
export function StartSupportSession({
  user,
  onClose,
}: {
  user: Pick<PlatformUser, "id" | "email" | "full_name" | "organization_name">;
  onClose: () => void;
}) {
  const start = useStartImpersonation();
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"read_only" | "read_write">("read_only");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    start.mutate(
      { user_id: user.id, reason: reason.trim(), mode },
      {
        onSuccess: (handoff) => {
          // The code goes in the fragment, never the query string: a
          // fragment is not sent to the server, so it cannot land in an
          // access log, a proxy trace or a Referer header. The customer app
          // spends it on load and wipes it from history straight away.
          window.open(
            `${handoff.handoff_url}#code=${encodeURIComponent(handoff.code)}`,
            "_blank",
            "noopener,noreferrer",
          );
          onClose();
        },
        onError: (err: unknown) =>
          setError(
            err instanceof Error ? err.message : "Could not open the session",
          ),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink-900/30 p-4 sm:items-center">
      <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl ring-1 ring-ink-200">
        <h2 className="text-base font-semibold text-ink-900">
          Open {user.full_name}&rsquo;s account
        </h2>
        <p className="mt-1 text-xs text-ink-500">
          {user.email} · {user.organization_name}
        </p>

        <label className="mt-5 block text-xs font-medium text-ink-700">
          Why are you going in?
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            placeholder="Customer reports the agent hangs up on Hindi calls"
            className="mt-1.5 w-full rounded-lg border border-ink-300/70 bg-white px-3 py-2 text-sm text-ink-800 outline-none focus:border-brand-600"
          />
        </label>
        <p className="mt-1 text-[0.7rem] text-ink-400">
          Written into the customer&rsquo;s own activity timeline — they can
          read it. At least 12 characters.
        </p>

        <fieldset className="mt-4">
          <legend className="text-xs font-medium text-ink-700">
            What may this session do?
          </legend>
          <div className="mt-2 grid gap-2">
            {(
              [
                [
                  "read_only",
                  "Look only",
                  "Nothing can be changed. Right for almost every question.",
                ],
                [
                  "read_write",
                  "Look and fix",
                  "Can change settings and agents. Still cannot spend credits, place calls or send messages.",
                ],
              ] as const
            ).map(([value, label, hint]) => (
              <label
                key={value}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                  mode === value
                    ? "border-brand-600 bg-brand-50"
                    : "border-ink-200 hover:bg-ink-50"
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  checked={mode === value}
                  onChange={() => setMode(value)}
                  className="mt-0.5 accent-brand-700"
                />
                <span>
                  <span className="block text-sm font-medium text-ink-900">
                    {label}
                  </span>
                  <span className="mt-0.5 block text-[0.7rem] leading-relaxed text-ink-500">
                    {hint}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {error && (
          <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <p className="mt-4 text-[0.7rem] leading-relaxed text-ink-400">
          The session lasts 30 minutes and cannot be extended. Everything you do
          is recorded against your name, not the customer&rsquo;s.
        </p>

        <div className="mt-4 flex justify-end gap-2">
          <Action onClick={onClose}>Cancel</Action>
          <Action
            onClick={submit}
            tone="primary"
            busy={start.isPending}
            disabled={reason.trim().length < 12}
          >
            Open account
          </Action>
        </div>
      </div>
    </div>
  );
}

export function SupportSessions() {
  const { data: sessions, isLoading } = useImpersonationSessions();
  const end = useEndImpersonation();

  const rows = sessions ?? [];
  const live = rows.filter((session) => session.is_active);

  return (
    <div>
      <PageTitle
        title="Support sessions"
        description="Every time staff have opened a customer's account, and what they did while they were in there."
      />

      {live.length > 0 && (
        <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-medium text-amber-900">
            {live.length} session{live.length === 1 ? "" : "s"} open right now
          </p>
          <p className="mt-0.5 text-xs text-amber-800">
            Anyone here can end any of them — including one someone walked away
            from.
          </p>
        </div>
      )}

      <Panel>
        {isLoading ? (
          <p className="py-16 text-center text-sm text-ink-400">Loading…</p>
        ) : rows.length === 0 ? (
          <Empty
            title="No support sessions yet"
            hint="Open one from a customer's profile or the user list when you need to see what they see."
          />
        ) : (
          <Grid
            headers={["Staff", "Account", "Reason", "Mode", "Started", "", ""]}
          >
            {rows.map((session) => {
              const left = remaining(session);
              return (
                <tr key={session.id} className="hover:bg-ink-50">
                  <td className="py-3 pl-4 pr-3">
                    <p className="font-medium text-ink-900">
                      {session.admin_email}
                    </p>
                    {session.started_ip && (
                      <p className="mt-0.5 text-[0.7rem] text-ink-400">
                        from {session.started_ip}
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <p className="text-ink-900">{session.organization_name}</p>
                    <p className="mt-0.5 text-[0.7rem] text-ink-400">
                      as {session.target_email}
                    </p>
                  </td>
                  <td className="min-w-[15rem] px-3 py-3 text-xs leading-relaxed text-ink-600">
                    {session.reason}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1">
                      <Pill value={session.mode} />
                      {/* Zero is worth saying out loud: it is the difference
                          between "staff looked" and "staff changed things". */}
                      <Pill
                        value={
                          session.writes_performed === 0
                            ? "no writes"
                            : `${session.writes_performed} writes`
                        }
                      />
                    </div>
                  </td>
                  <td className="px-3 py-3 text-xs text-ink-500">
                    {formatDateTime(session.created_at)}
                  </td>
                  <td className="px-3 py-3 text-xs">
                    {left !== null ? (
                      <span className="font-medium text-amber-700">
                        {left} min left
                      </span>
                    ) : (
                      <span className="text-ink-400">
                        {session.end_reason?.replace(/_/g, " ") ?? "ended"}
                      </span>
                    )}
                  </td>
                  <td className="py-3 pl-3 pr-4 text-right">
                    {session.is_active && (
                      <Action
                        tone="danger"
                        busy={end.isPending}
                        onClick={() => end.mutate(session.id)}
                      >
                        End now
                      </Action>
                    )}
                  </td>
                </tr>
              );
            })}
          </Grid>
        )}
      </Panel>
    </div>
  );
}
