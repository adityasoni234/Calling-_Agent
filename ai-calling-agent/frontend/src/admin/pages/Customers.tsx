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
                <tr key={org.id} className="hover:bg-ink-50">
                  <td className="py-3 pl-4 pr-3">
                    <p className="font-medium text-ink-900">{org.name}</p>
                    <p className="mt-0.5 text-[0.7rem] text-ink-400">
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
                          ? "text-red-700"
                          : org.credit_balance < 500
                            ? "text-amber-700"
                            : "text-ink-900"
                      }`}
                    >
                      {org.credit_balance.toFixed(0)}
                    </span>
                    <span className="ml-1.5 text-[0.7rem] text-ink-400">
                      {money(org.credit_balance)}
                    </span>
                  </td>
                  <td className="px-3 py-3 tabular-nums text-ink-700">
                    {org.calls_30d}
                    <span className="ml-1.5 text-[0.7rem] text-ink-400">
                      {org.minutes_30d}m
                    </span>
                  </td>
                  <td className="px-3 py-3 tabular-nums text-ink-500">
                    ${org.provider_cost_usd.toFixed(2)}
                  </td>
                  <td
                    className={`px-3 py-3 tabular-nums ${
                      margin >= 0 ? "text-emerald-700" : "text-red-700"
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
                        className="whitespace-nowrap rounded-md border border-ink-300/70 px-2 py-1 text-[0.7rem] font-medium text-ink-700 transition-colors hover:bg-ink-100"
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
                <td className="whitespace-nowrap py-2.5 pl-4 pr-3 text-[0.7rem] text-ink-400">
                  {formatDateTime(entry.created_at)}
                </td>
                <td className="px-3 py-2.5">
                  <Pill value={entry.kind} />
                </td>
                <td
                  className={`px-3 py-2.5 tabular-nums ${
                    entry.amount < 0 ? "text-ink-500" : "text-emerald-700"
                  }`}
                >
                  {entry.amount > 0 ? "+" : ""}
                  {entry.amount.toFixed(2)}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-800">
                  {entry.balance_after.toFixed(0)}
                </td>
                <td className="px-3 py-2.5 text-[0.7rem] text-ink-400">
                  {entry.note ?? "—"}
                  {entry.provider_cost_usd != null && (
                    <span className="ml-1.5 text-ink-400">
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
