import { useState } from "react";

import { usePriceBooks, usePublishBook, useSaveRule } from "@/admin/hooks";
import {
  Action,
  Empty,
  Grid,
  Metric,
  PageTitle,
  Panel,
  Pill,
} from "@/admin/ui";
import type { PriceBook } from "@/types/api";

/**
 * Price books.
 *
 * A published book is read-only here, and that is the point: editing a live
 * rule would change what last month's calls cost. Repricing means a new
 * version, and every charge records the rule id it was computed from.
 *
 * Margin is shown per rule against the cost recorded when the rule was
 * written, so a stale cost assumption is visible rather than silently
 * flattering the number.
 */

const pct = (rate: string, cost: string | null, kind: string) => {
  // A cost-markup or percentage rule cannot be below cost by construction,
  // so there is no margin to compare -- the rate *is* the margin.
  if (kind === "cost_markup" || kind === "percent") return null;
  if (!cost) return null;
  const r = Number.parseFloat(rate);
  const c = Number.parseFloat(cost);
  if (!Number.isFinite(r) || r <= 0) return null;
  return ((r - c) / r) * 100;
};

/**
 * A rate is not always money.
 *
 * COST_MARKUP carries a multiplier and PERCENT a percentage, so rendering
 * either with a dollar sign reads as a $3.00 charge per AI call rather than
 * a 3x markup. Only the per-unit kinds are currency.
 */
const rateText = (rate: string, kind: string) => {
  const n = Number.parseFloat(rate);
  if (!Number.isFinite(n)) return rate;
  if (kind === "cost_markup") return `${n}x cost`;
  if (kind === "percent") return `${n}%`;
  return `$${n.toFixed(4)}`;
};

const label = (billable: string) =>
  billable.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());

export function Pricing() {
  const books = usePriceBooks();
  const save = useSaveRule();
  const publish = usePublishBook();
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const rows = books.data ?? [];
  const published = rows.filter((b) => b.status === "published");
  const risky = rows.filter((b) => b.below_cost.length > 0);

  const doPublish = async (book: PriceBook) => {
    setError(null);
    let reason: string | undefined;
    if (book.below_cost.length) {
      // Selling below cost has to be a decision someone signed, so the
      // reason is collected here and stored on the book.
      const given = prompt(
        `${book.name} prices ${book.below_cost.join(", ")} below recorded cost.\n\n` +
          "Publishing anyway needs a written reason, which is kept on the book.",
      );
      if (!given || given.trim().length < 5) return;
      reason = given;
    }
    try {
      await publish.mutateAsync({ bookId: book.id, reason });
    } catch (err) {
      setError((err as Error)?.message ?? "Could not publish that book");
    }
  };

  return (
    <div>
      <PageTitle
        title="Pricing"
        description="What customers are charged. A published book is immutable; repricing creates a new version."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Metric
          label="Published"
          value={String(published.length)}
          sub={`${rows.length} books`}
        />
        <Metric
          label="Below cost"
          value={String(risky.length)}
          sub="Blocked from publishing without a reason"
          tone={risky.length ? "bad" : "good"}
        />
        <Metric
          label="Default book"
          value={rows.find((b) => b.is_default)?.name ?? "none"}
        />
      </div>

      {error && (
        <p className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[0.8rem] text-red-300">
          {error}
        </p>
      )}

      {books.isPending ? (
        <Empty title="Loading…" />
      ) : !rows.length ? (
        <Empty
          title="No price books"
          hint="Run scripts/seed_price_books.py to create them."
        />
      ) : (
        <div className="space-y-4">
          {rows.map((book) => (
            <Panel
              key={book.id}
              title={`${book.name} · v${book.version}`}
              description={book.description ?? book.slug}
              actions={
                <div className="flex items-center gap-2">
                  {book.is_default && <Pill value="default" />}
                  <Pill value={book.status} />
                  {book.status === "draft" && (
                    <Action
                      tone="primary"
                      busy={publish.isPending}
                      onClick={() => void doPublish(book)}
                    >
                      Publish
                    </Action>
                  )}
                </div>
              }
            >
              {book.below_cost_reason && (
                <p className="border-b border-ink-200/60 px-4 py-2 text-[0.75rem] text-amber-700">
                  Published below cost: {book.below_cost_reason}
                </p>
              )}
              {!book.rules.length ? (
                <Empty title="No rules yet" />
              ) : (
                <Grid
                  headers={[
                    "Billable",
                    "Type",
                    "Rate",
                    "Our cost",
                    "Margin",
                    "Min",
                    "",
                  ]}
                >
                  {book.rules.map((rule) => {
                    const margin = pct(
                      rule.rate,
                      rule.assumed_cost,
                      rule.rate_kind,
                    );
                    const key = `${book.id}:${rule.id}`;
                    return (
                      <tr key={rule.id} className="text-ink-700">
                        <td className="py-2.5 pl-4 pr-3">
                          <p className="text-ink-900">{label(rule.billable)}</p>
                          {rule.notes && (
                            <p className="mt-0.5 max-w-md text-[0.65rem] text-ink-400">
                              {rule.notes}
                            </p>
                          )}
                        </td>
                        <td className="px-3 text-[0.7rem] text-ink-500">
                          {rule.rate_kind.replace(/_/g, " ")}
                        </td>
                        <td className="px-3 tabular-nums">
                          {editing === key ? (
                            <input
                              autoFocus
                              value={value}
                              onChange={(e) => setValue(e.target.value)}
                              onBlur={() => {
                                if (value && value !== rule.rate) {
                                  save.mutate({
                                    bookId: book.id,
                                    rule: {
                                      billable: rule.billable,
                                      region: rule.region,
                                      rate_kind: rule.rate_kind,
                                      rate: value,
                                      assumed_cost: rule.assumed_cost,
                                      minimum_charge: rule.minimum_charge,
                                      increment_seconds: rule.increment_seconds,
                                      notes: rule.notes,
                                    },
                                  });
                                }
                                setEditing(null);
                              }}
                              className="w-24 rounded border border-ink-300 bg-ink-50 px-1.5 py-0.5 text-ink-900"
                            />
                          ) : (
                            <button
                              type="button"
                              disabled={book.status === "published"}
                              onClick={() => {
                                setEditing(key);
                                setValue(rule.rate);
                              }}
                              className="tabular-nums hover:text-ink-900 disabled:cursor-not-allowed"
                              title={
                                book.status === "published"
                                  ? "Published books are immutable"
                                  : "Click to edit"
                              }
                            >
                              {rateText(rule.rate, rule.rate_kind)}
                            </button>
                          )}
                        </td>
                        <td className="px-3 tabular-nums text-ink-400">
                          {rule.assumed_cost
                            ? `$${Number.parseFloat(rule.assumed_cost).toFixed(4)}`
                            : "—"}
                        </td>
                        <td
                          className={`px-3 tabular-nums ${
                            margin === null
                              ? "text-ink-400"
                              : margin < 0
                                ? "text-red-700"
                                : margin < 30
                                  ? "text-amber-700"
                                  : "text-emerald-700"
                          }`}
                        >
                          {margin !== null
                            ? `${margin.toFixed(0)}%`
                            : rule.rate_kind === "cost_markup" ||
                                rule.rate_kind === "percent"
                              ? // Priced off cost, so the rate is the margin.
                                "by design"
                              : "unknown"}
                        </td>
                        <td className="px-3 tabular-nums text-ink-400">
                          {rule.minimum_charge
                            ? `$${Number.parseFloat(rule.minimum_charge).toFixed(2)}`
                            : "—"}
                        </td>
                        <td />
                      </tr>
                    );
                  })}
                </Grid>
              )}
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
