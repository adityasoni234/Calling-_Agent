import { useState } from "react";

import {
  useAdminPackages,
  useCreatePackage,
  useRetirePackage,
  useUpdatePackage,
} from "@/admin/hooks";
import {
  Action,
  Empty,
  Grid,
  Metric,
  PageTitle,
  Panel,
  Pill,
} from "@/admin/ui";
import { formatMinor } from "@/lib/format";

import type { AdminPackage, AdminPackageWrite } from "@/types/api";

/**
 * What customers can buy.
 *
 * Prices are entered in dollars and cents here but stored as integer minor
 * units, because float arithmetic on money eventually produces a bill nobody
 * can reconcile. Tax is basis points for the same reason: 18% is 1800.
 */

const BLANK: AdminPackageWrite = {
  name: "",
  slug: "",
  description: "",
  price_minor: 0,
  currency: "USD",
  tax_bps: 1800,
  base_credits: 0,
  bonus_credits: 0,
  is_active: true,
  is_public: true,
  display_order: 0,
};

/** Minor units as a plain decimal, for the price input's value. */
const majorUnits = (minor: number) => (minor / 100).toFixed(2);
const money = (minor: number, currency = "USD") => formatMinor(minor, currency);

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export function Packages() {
  const packages = useAdminPackages();
  const create = useCreatePackage();
  const update = useUpdatePackage();
  const retire = useRetirePackage();

  const [editing, setEditing] = useState<AdminPackage | null>(null);
  const [draft, setDraft] = useState<AdminPackageWrite | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rows = packages.data ?? [];
  const live = rows.filter((p) => p.is_active);
  const revenue = rows.reduce((sum, p) => sum + p.revenue_minor, 0);

  const openNew = () => {
    setEditing(null);
    setDraft({ ...BLANK });
    setError(null);
  };

  const openEdit = (pkg: AdminPackage) => {
    setEditing(pkg);
    setError(null);
    setDraft({
      name: pkg.name,
      slug: pkg.slug,
      description: pkg.description ?? "",
      price_minor: pkg.price_minor,
      currency: pkg.currency,
      tax_bps: pkg.tax_bps,
      base_credits: pkg.base_credits,
      bonus_credits: pkg.bonus_credits,
      validity_days: pkg.validity_days,
      is_active: pkg.is_active,
      is_public: pkg.is_public,
      display_order: pkg.display_order,
      max_per_organization: pkg.max_per_organization,
    });
  };

  const save = async () => {
    if (!draft) return;
    setError(null);
    const body: AdminPackageWrite = {
      ...draft,
      slug: draft.slug || slugify(draft.name),
      description: draft.description || null,
    };
    try {
      if (editing) await update.mutateAsync({ id: editing.id, body });
      else await create.mutateAsync(body);
      setDraft(null);
      setEditing(null);
    } catch (err) {
      setError((err as Error)?.message ?? "Could not save that package");
    }
  };

  const field = (key: keyof AdminPackageWrite, value: unknown) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  const input =
    "w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-[0.8rem] text-slate-100 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none";
  const label =
    "block text-[0.65rem] font-medium uppercase tracking-[0.1em] text-slate-500";

  // Shown live while editing, so the operator sees the price a customer sees.
  const currency = draft?.currency ?? "USD";
  const previewTax = draft
    ? Math.round((draft.price_minor * (draft.tax_bps ?? 0)) / 10_000)
    : 0;

  return (
    <div>
      <PageTitle
        title="Packages"
        description="Prices and credit amounts customers can buy. Changes never alter orders already placed."
        actions={
          <Action tone="primary" onClick={openNew}>
            New package
          </Action>
        }
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Metric
          label="Live packages"
          value={String(live.length)}
          sub={`${rows.length} total`}
        />
        <Metric
          label="Lifetime revenue"
          value={money(revenue)}
          sub="Paid orders, before refunds"
          tone="good"
        />
        <Metric
          label="Paid orders"
          value={String(rows.reduce((sum, p) => sum + p.orders_paid, 0))}
        />
      </div>

      {draft && (
        <Panel
          title={editing ? `Edit ${editing.name}` : "New package"}
          description="Price in dollars, credits as whole numbers. One credit is one US cent of list price."
        >
          <div className="space-y-4 px-4 py-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className={label} htmlFor="pkg-name">
                  Name
                </label>
                <input
                  id="pkg-name"
                  className={`mt-1 ${input}`}
                  value={draft.name}
                  placeholder="Starter"
                  onChange={(e) => {
                    const name = e.target.value;
                    setDraft((current) =>
                      current
                        ? {
                            ...current,
                            name,
                            // Only auto-fill while the slug is untouched: editing
                            // a live package's slug would orphan its URL.
                            slug: editing ? current.slug : slugify(name),
                          }
                        : current,
                    );
                  }}
                />
              </div>
              <div>
                <label className={label} htmlFor="pkg-slug">
                  Slug
                </label>
                <input
                  id="pkg-slug"
                  className={`mt-1 ${input} font-mono`}
                  value={draft.slug}
                  placeholder="starter"
                  onChange={(e) => field("slug", e.target.value)}
                />
              </div>
            </div>

            <div>
              <label className={label} htmlFor="pkg-desc">
                Description
              </label>
              <input
                id="pkg-desc"
                className={`mt-1 ${input}`}
                value={draft.description ?? ""}
                placeholder="Roughly 1,500 minutes of Indian calling"
                onChange={(e) => field("description", e.target.value)}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-4">
              <div>
                <label className={label} htmlFor="pkg-price">
                  Price ({currency})
                </label>
                <input
                  id="pkg-price"
                  type="number"
                  step="0.01"
                  min="0"
                  className={`mt-1 ${input} tabular-nums`}
                  value={majorUnits(draft.price_minor)}
                  onChange={(e) =>
                    field(
                      "price_minor",
                      Math.round(Number(e.target.value || 0) * 100),
                    )
                  }
                />
              </div>
              <div>
                <label className={label} htmlFor="pkg-tax">
                  Tax %
                </label>
                <input
                  id="pkg-tax"
                  type="number"
                  step="0.01"
                  min="0"
                  className={`mt-1 ${input} tabular-nums`}
                  value={(draft.tax_bps ?? 0) / 100}
                  onChange={(e) =>
                    field(
                      "tax_bps",
                      Math.round(Number(e.target.value || 0) * 100),
                    )
                  }
                />
              </div>
              <div>
                <label className={label} htmlFor="pkg-base">
                  Credits
                </label>
                <input
                  id="pkg-base"
                  type="number"
                  min="0"
                  className={`mt-1 ${input} tabular-nums`}
                  value={draft.base_credits}
                  onChange={(e) =>
                    field(
                      "base_credits",
                      Math.round(Number(e.target.value || 0)),
                    )
                  }
                />
              </div>
              <div>
                <label className={label} htmlFor="pkg-bonus">
                  Bonus credits
                </label>
                <input
                  id="pkg-bonus"
                  type="number"
                  min="0"
                  className={`mt-1 ${input} tabular-nums`}
                  value={draft.bonus_credits ?? 0}
                  onChange={(e) =>
                    field(
                      "bonus_credits",
                      Math.round(Number(e.target.value || 0)),
                    )
                  }
                />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-4">
              <div>
                <label className={label} htmlFor="pkg-validity">
                  Validity (days)
                </label>
                <input
                  id="pkg-validity"
                  type="number"
                  min="1"
                  placeholder="never expires"
                  className={`mt-1 ${input} tabular-nums`}
                  value={draft.validity_days ?? ""}
                  onChange={(e) =>
                    field(
                      "validity_days",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                />
              </div>
              <div>
                <label className={label} htmlFor="pkg-order">
                  Display order
                </label>
                <input
                  id="pkg-order"
                  type="number"
                  min="0"
                  className={`mt-1 ${input} tabular-nums`}
                  value={draft.display_order ?? 0}
                  onChange={(e) =>
                    field("display_order", Number(e.target.value || 0))
                  }
                />
              </div>
              <label className="flex items-end gap-2 pb-2 text-[0.8rem] text-slate-300">
                <input
                  type="checkbox"
                  checked={draft.is_active ?? true}
                  onChange={(e) => field("is_active", e.target.checked)}
                />
                Active
              </label>
              <label className="flex items-end gap-2 pb-2 text-[0.8rem] text-slate-300">
                <input
                  type="checkbox"
                  checked={draft.is_public ?? true}
                  onChange={(e) => field("is_public", e.target.checked)}
                />
                Listed publicly
              </label>
            </div>

            <p className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-[0.75rem] text-slate-400">
              Customer pays{" "}
              <span className="tabular-nums text-slate-100">
                {money(draft.price_minor + previewTax, currency)}
              </span>{" "}
              for{" "}
              <span className="tabular-nums text-slate-100">
                {(
                  draft.base_credits + (draft.bonus_credits ?? 0)
                ).toLocaleString()}
              </span>{" "}
              credits — {money(draft.price_minor, currency)} +{" "}
              {money(previewTax, currency)} tax.
            </p>

            {error && (
              <p className="rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-[0.75rem] text-red-300">
                {error}
              </p>
            )}

            <div className="flex gap-2">
              <Action
                tone="primary"
                busy={create.isPending || update.isPending}
                onClick={() => void save()}
              >
                {editing ? "Save changes" : "Create package"}
              </Action>
              <Action
                onClick={() => {
                  setDraft(null);
                  setEditing(null);
                }}
              >
                Cancel
              </Action>
            </div>
          </div>
        </Panel>
      )}

      <div className="mt-5">
        <Panel title="All packages">
          {packages.isPending ? (
            <Empty title="Loading…" />
          ) : !rows.length ? (
            <Empty
              title="No packages yet"
              hint="Customers cannot buy credits until at least one package is active."
            />
          ) : (
            <Grid
              headers={[
                "Package",
                "Price",
                "Credits",
                "Sold",
                "Revenue",
                "Status",
                "",
              ]}
            >
              {rows.map((pkg) => (
                <tr key={pkg.id} className="text-slate-300">
                  <td className="py-2.5 pl-4 pr-3">
                    <p className="text-slate-100">{pkg.name}</p>
                    <p className="font-mono text-[0.65rem] text-slate-500">
                      {pkg.slug}
                    </p>
                  </td>
                  <td className="whitespace-nowrap px-3 tabular-nums">
                    {money(pkg.payable_minor, pkg.currency)}
                    <span className="ml-1 text-[0.65rem] text-slate-500">
                      incl {pkg.tax_bps / 100}%
                    </span>
                  </td>
                  <td className="px-3 tabular-nums">
                    {pkg.total_credits.toLocaleString()}
                    {pkg.bonus_credits > 0 && (
                      <span className="ml-1 text-[0.65rem] text-emerald-400">
                        +{pkg.bonus_credits.toLocaleString()}
                      </span>
                    )}
                  </td>
                  <td className="px-3 tabular-nums">{pkg.orders_paid}</td>
                  <td className="px-3 tabular-nums">
                    {money(pkg.revenue_minor, pkg.currency)}
                  </td>
                  <td className="px-3">
                    <div className="flex gap-1">
                      <Pill value={pkg.is_active ? "active" : "inactive"} />
                      {!pkg.is_public && <Pill value="hidden" />}
                    </div>
                  </td>
                  <td className="px-3">
                    <div className="flex justify-end gap-1.5">
                      <Action onClick={() => openEdit(pkg)}>Edit</Action>
                      {pkg.is_active && (
                        <Action
                          tone="danger"
                          busy={retire.isPending}
                          onClick={() => void retire.mutateAsync(pkg.id)}
                        >
                          Retire
                        </Action>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </Grid>
          )}
        </Panel>
      </div>
    </div>
  );
}
