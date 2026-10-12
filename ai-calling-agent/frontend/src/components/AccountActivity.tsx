import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ui/Card";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ActivityEvent } from "@/types/api";

/**
 * The account's own audit trail, on the customer's Settings page.
 *
 * It exists chiefly for one row: `account.accessed_by_support`. Recording
 * staff access in a table only we can read is not the same as telling the
 * customer, so this is where they find out, with the reason the admin typed
 * and the time it happened.
 */
export function AccountActivity() {
  const { data, isLoading } = useQuery({
    queryKey: ["settings", "activity"],
    queryFn: () => api.get<ActivityEvent[]>("/settings/activity?limit=50"),
  });

  const events = data ?? [];
  const supportVisits = events.filter(
    (event) => event.actor_type === "platform_admin",
  );

  return (
    <Card
      title="Account activity"
      description="Who changed what, and when — including any time Stockvala support opened your account."
    >
      {supportVisits.length > 0 && (
        <p className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs leading-relaxed text-amber-900">
          Stockvala support has opened this account {supportVisits.length} time
          {supportVisits.length === 1 ? "" : "s"}. Each visit is listed below
          with the reason given. If one looks wrong, tell us.
        </p>
      )}

      {isLoading ? (
        <p className="py-8 text-center text-sm text-ink-400">Loading…</p>
      ) : events.length === 0 ? (
        <p className="py-8 text-center text-sm text-ink-500">
          Nothing recorded yet. Changes to agents, campaigns and integrations
          will appear here.
        </p>
      ) : (
        <ul className="divide-y divide-ink-200/60">
          {events.map((event) => (
            <li
              key={event.id}
              className="flex flex-col gap-1 py-3 sm:flex-row sm:gap-4"
            >
              <span className="shrink-0 text-xs tabular-nums text-ink-400 sm:w-40">
                {formatDateTime(event.created_at)}
              </span>
              <div className="min-w-0">
                <p className="text-sm leading-relaxed text-ink-800">
                  {event.summary ?? event.action.replace(/[._]/g, " ")}
                </p>
                <p className="mt-0.5 text-xs text-ink-400">
                  {event.actor_label ?? "Stockvala"}
                  {event.actor_type === "platform_admin" && (
                    <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[0.65rem] font-medium text-amber-900">
                      support
                    </span>
                  )}
                </p>
                {event.reason && (
                  <p className="mt-1 text-xs italic leading-relaxed text-ink-500">
                    “{event.reason}”
                  </p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
