import { useState } from "react";

import {
  useActivateUser,
  useDeactivateUser,
  usePlatformUsers,
} from "@/admin/hooks";
import { Action, Empty, Grid, PageTitle, Panel, Pill } from "@/admin/ui";
import { formatDateTime } from "@/lib/format";

export function Users() {
  const { data: users, isLoading } = usePlatformUsers();
  const deactivate = useDeactivateUser();
  const activate = useActivateUser();
  const [note, setNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const rows = (users ?? []).filter((user) =>
    `${user.email} ${user.full_name} ${user.organization_name}`
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  );

  return (
    <div>
      <PageTitle
        title="Users"
        description="Everyone with a sign-in, across every customer."
        actions={
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name, email, customer"
            className="rounded-lg border border-ink-300/70 bg-white px-3 py-1.5 text-xs text-ink-800 outline-none focus:border-brand-600"
          />
        }
      />

      {note && (
        <p className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-300">
          {note}
        </p>
      )}

      <Panel>
        {isLoading ? (
          <p className="py-16 text-center text-sm text-ink-400">Loading…</p>
        ) : rows.length === 0 ? (
          <Empty title="No users match" />
        ) : (
          <Grid
            headers={["User", "Customer", "Role", "Last sign-in", "Status", ""]}
          >
            {rows.map((user) => (
              <tr key={user.id} className="hover:bg-ink-50">
                <td className="py-3 pl-4 pr-3">
                  <p className="font-medium text-ink-900">{user.full_name}</p>
                  <p className="mt-0.5 text-[0.7rem] text-ink-400">
                    {user.email}
                  </p>
                </td>
                <td className="px-3 py-3 text-ink-700">
                  {user.organization_name}
                </td>
                <td className="px-3 py-3">
                  <div className="flex gap-1">
                    <Pill value={user.role} />
                    {user.is_platform_admin && <Pill value="platform admin" />}
                  </div>
                </td>
                <td className="px-3 py-3 text-[0.7rem] text-ink-400">
                  {user.last_login_at
                    ? formatDateTime(user.last_login_at)
                    : "never"}
                </td>
                <td className="px-3 py-3">
                  <Pill value={user.is_active ? "active" : "inactive"} />
                </td>
                <td className="px-3 py-3 text-right">
                  {user.is_active ? (
                    <Action
                      tone="danger"
                      busy={deactivate.isPending}
                      onClick={async () => {
                        if (!confirm(`Stop ${user.email} signing in?`)) return;
                        setNote(
                          (await deactivate.mutateAsync({ id: user.id }))
                            .message,
                        );
                      }}
                    >
                      Deactivate
                    </Action>
                  ) : (
                    <Action
                      busy={activate.isPending}
                      onClick={async () =>
                        setNote(
                          (await activate.mutateAsync({ id: user.id })).message,
                        )
                      }
                    >
                      Reactivate
                    </Action>
                  )}
                </td>
              </tr>
            ))}
          </Grid>
        )}
      </Panel>
    </div>
  );
}
