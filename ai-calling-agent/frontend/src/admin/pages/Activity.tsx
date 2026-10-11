import { usePlatformEvents } from "@/admin/hooks";
import { Empty, Grid, PageTitle, Panel, Pill } from "@/admin/ui";
import { formatDateTime } from "@/lib/format";

export function Activity() {
  const { data: events, isLoading } = usePlatformEvents();

  return (
    <div>
      <PageTitle
        title="Activity"
        description="Every administrative action, attributable to a person. Nothing here can be edited."
      />
      <Panel>
        {isLoading ? (
          <p className="py-16 text-center text-sm text-slate-500">Loading…</p>
        ) : !events?.length ? (
          <Empty
            title="Nothing yet"
            hint="Granting credits, suspending a customer or disabling a user all appear here."
          />
        ) : (
          <Grid headers={["When", "Who", "Action", "Target", "Detail"]}>
            {events.map((event) => (
              <tr key={event.id} className="hover:bg-slate-800/40">
                <td className="whitespace-nowrap py-2.5 pl-4 pr-3 text-[0.7rem] text-slate-500">
                  {formatDateTime(event.created_at)}
                </td>
                <td className="px-3 py-2.5 text-slate-300">
                  {event.actor_email}
                </td>
                <td className="px-3 py-2.5">
                  <Pill value={event.action} />
                </td>
                <td className="px-3 py-2.5 text-slate-300">
                  {event.target ?? "—"}
                </td>
                <td className="px-3 py-2.5 text-[0.7rem] text-slate-500">
                  {event.detail ?? "—"}
                </td>
              </tr>
            ))}
          </Grid>
        )}
      </Panel>
    </div>
  );
}
