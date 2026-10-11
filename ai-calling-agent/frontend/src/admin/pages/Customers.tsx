import { useState } from "react";
import { Link } from "react-router-dom";

import {
  useCreditHistory,
  useDeductCredits,
  useGrantCredits,
  usePlatformOrganizations,
  useSuspendOrganization,
  useUnsuspendOrganization,
} from "@/admin/hooks";
import { Action, Empty, Grid, PageTitle, Panel, Pill } from "@/admin/ui";
import { money } from "@/admin/format";
import { formatDateTime } from "@/lib/format";
import type { OrganizationSummary } from "@/types/api";

export function Customers() {
  const { data: organizations, isLoading } = usePlatformOrganizations();
  const grant = useGrantCredits();
  const deduct = useDeductCredits();
  const suspend = useSuspendOrganization();
  const unsuspend = useUnsuspendOrganization();

  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState<OrganizationSummary | null>(null);
  const [search, setSearch] = useState("");

  const rows = (organizations ?? []).filter((org) =>
    org.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  const run = async (
    mutation: {
      mutateAsync: (v: {
        id: string;
        body?: never;
      }) => Promise<{ message: string }>;
    },
    id: string,
    body?: unknown,
  ) =>
    setNote((await mutation.mutateAsync({ id, body: body as never })).message);

  return (
    <div>
      <PageTitle
        title="Customers"
        description="Every organization on the platform, what they use, and what it costs us."
        actions={
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search customers"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-slate-500"
          />
        }
      />

      {note && (
        <p className="mb-4 rounded-lg border border-emerald-900/60 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300">
          {note}
        </p>
      )}

      <Panel>
        {isLoading ? (
          <p className="py-16 text-center text-sm text-slate-500">Loading…</p>
        ) : rows.length === 0 ? (
          <Empty title="No customers match" />
        ) : (
          <Grid
            headers={[
              "Customer",
              "Plan",
              "Balance",
              "Calls · 30d",
              "Our cost",
              "Margin",
              "Status",
              "",
            ]}
          >
            {rows.map((org) => {
              // Both sides of this subtraction must cover the same 30 days.
              // Lifetime billing against a month of cost reported a loss on
              // every account that had been quiet lately.
              const billed = org.credits_used_30d / 100;
              const margin = billed - org.provider_cost_usd;
              return (
                <tr key={org.id} className="hover:bg-slate-800/40">
                  <td className="py-3 pl-4 pr-3">
                    <p className="font-medium text-slate-100">{org.name}</p>
                    <p className="mt-0.5 text-[0.7rem] text-slate-500">
                      {org.users} user{org.users === 1 ? "" : "s"} ·{" "}
                      {org.last_call_at
                        ? `last call ${formatDateTime(org.last_call_at)}`
                        : "never called"}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <Pill value={org.plan} />
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className={`font-medium tabular-nums ${
                        org.credit_balance <= 0
                          ? "text-red-400"
                          : org.credit_balance < 500
                            ? "text-amber-400"
                            : "text-slate-100"
                      }`}
                    >
                      {org.credit_balance.toFixed(0)}
                    </span>
                    <span className="ml-1.5 text-[0.7rem] text-slate-500">
                      {money(org.credit_balance)}
                    </span>
                  </td>
                  <td className="px-3 py-3 tabular-nums text-slate-300">
                    {org.calls_30d}
                    <span className="ml-1.5 text-[0.7rem] text-slate-500">
                      {org.minutes_30d}m
                    </span>
                  </td>
                  <td className="px-3 py-3 tabular-nums text-slate-400">
                    ${org.provider_cost_usd.toFixed(2)}
                  </td>
                  <td
                    className={`px-3 py-3 tabular-nums ${
                      margin >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    ${margin.toFixed(2)}
                  </td>
                  <td className="px-3 py-3">
                    <span title={org.suspended_reason ?? ""}>
                      <Pill value={org.is_suspended ? "suspended" : "active"} />
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex justify-end gap-1">
                      <Action
                        tone="primary"
                        busy={grant.isPending}
                        onClick={() => {
                          const raw = prompt(
                            `Add credits to ${org.name}.\n\n100 credits = $1.00\nCurrent balance: ${org.credit_balance.toFixed(0)}`,
                            "5000",
                          );
                          const credits = Number(raw);
                          if (!raw || !Number.isFinite(credits) || credits <= 0)
                            return;
                          run(grant, org.id, {
                            credits,
                            note:
                              prompt("Note (invoice number, reason)", "") ?? "",
                          });
                        }}
                      >
                        Add credits
                      </Action>
                      <Action
                        busy={deduct.isPending}
                        onClick={() => {
                          const raw = prompt(
                            `Remove credits from ${org.name}.`,
                            "0",
                          );
                          const credits = Number(raw);
                          if (!raw || !Number.isFinite(credits) || credits <= 0)
                            return;
                          // The server requires a reason too; asking here avoids
                          // a round trip that only fails.
                          const reason = prompt("Reason (required)");
                          if (!reason || reason.trim().length < 3) return;
                          run(deduct, org.id, { credits, note: reason });
                        }}
                      >
                        Remove
                      </Action>
                      <Link
                        to={`/customers/${org.id}`}
                        className="whitespace-nowrap rounded-md border border-slate-700 px-2 py-1 text-[0.7rem] font-medium text-slate-300 transition-colors hover:bg-slate-800"
                      >
                        Open
                      </Link>
                      <Action
                        onClick={() =>
                          setOpen(open?.id === org.id ? null : org)
                        }
                      >
                        Statement
                      </Action>
                      {org.is_suspended ? (
                        <Action
                          busy={unsuspend.isPending}
                          onClick={() => run(unsuspend, org.id)}
                        >
                          Reinstate
                        </Action>
                      ) : (
                        <Action
                          tone="danger"
                          busy={suspend.isPending}
                          onClick={() => {
                            const reason = prompt(
                              `Suspend ${org.name}?\n\nThey will not be able to start any calls.\n\nReason:`,
                            );
                            if (!reason || reason.trim().length < 3) return;
                            run(suspend, org.id, { reason });
                          }}
                        >
                          Suspend
                        </Action>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </Grid>
        )}
      </Panel>

      {open && <Statement organization={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Statement({
  organization,
  onClose,
}: {
  organization: OrganizationSummary;
  onClose: () => void;
}) {
  const { data: entries } = useCreditHistory(organization.id);
  return (
    <div className="mt-4">
      <Panel
        title={`${organization.name} — credit statement`}
        description="Every movement, newest first. The balance is their sum."
        actions={<Action onClick={onClose}>Close</Action>}
      >
        {!entries?.length ? (
          <Empty title="No credit movements yet" />
        ) : (
          <Grid headers={["When", "Type", "Amount", "Balance after", "Note"]}>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td className="whitespace-nowrap py-2.5 pl-4 pr-3 text-[0.7rem] text-slate-500">
                  {formatDateTime(entry.created_at)}
                </td>
                <td className="px-3 py-2.5">
                  <Pill value={entry.kind} />
                </td>
                <td
                  className={`px-3 py-2.5 tabular-nums ${
                    entry.amount < 0 ? "text-slate-400" : "text-emerald-400"
                  }`}
                >
                  {entry.amount > 0 ? "+" : ""}
                  {entry.amount.toFixed(2)}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-slate-200">
                  {entry.balance_after.toFixed(0)}
                </td>
                <td className="px-3 py-2.5 text-[0.7rem] text-slate-500">
                  {entry.note ?? "—"}
                  {entry.provider_cost_usd != null && (
                    <span className="ml-1.5 text-slate-600">
                      (cost ${entry.provider_cost_usd.toFixed(4)})
                    </span>
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
